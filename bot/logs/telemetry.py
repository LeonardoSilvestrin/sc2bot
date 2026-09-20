"""The event catalog: what each layer writes to the JSONL log, and when.

State summaries go through a `ChangeGate` (on change, plus a heartbeat).
Decisions never do: every posture change, proposal set, grant and command
change is written when it happens. ``docs/architecture.md`` lists
every event and its fields.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from sc2.position import Point2

from bot.attention import AttentionState, MapView, OpeningObservations, is_army
from bot.attention.opening import EMPTY as NO_OPENING
from bot.awareness import AwarenessState
from bot.body.behaviors.attack import MicroReport
from bot.body.behaviors.detection import DetectionReport
from bot.body.behaviors.economy import SpawnMode
from bot.body.behaviors.sensor_towers import SensorTowerReport
from bot.body.engine import EngineResult, rank
from bot.ego.missions import MissionView
from bot.ego.planners import (
    DetectionPlan,
    EarlyScoutReport,
    EconomyPlan,
    IntelPlan,
    Proposal,
    SensorTowerPlan,
    StructurePlan,
)
from bot.ego.planners.map_control import MapControlPlan, StagingPlan, StagingPoint
from bot.ego.planners.offense import LocalFight, OffensePlan
from bot.ego.strategy import GameAssessment, StrategicIntent

from .identity import describe_build, fingerprint
from .jsonl import BotLogger, ChangeGate

HEARTBEAT = 10.0
ATTENTION_HEARTBEAT = 5.0
# Coarse grid a moving target is compared on, so a drifting point is one command.
COMMAND_TARGET_CELL = 3.0
TOP_CONTACTS = 8
# The staging terms move with the field every frame: sampled, not change-logged.
MAP_CONTROL_HEARTBEAT = 30.0


class Telemetry:
    def __init__(self, logger: BotLogger, *, heartbeat: float = HEARTBEAT) -> None:
        self.logger = logger
        # Resources and supply move every frame: sampled, not change-logged.
        self._attention = ChangeGate(heartbeat=ATTENTION_HEARTBEAT)
        self._awareness = ChangeGate(heartbeat=heartbeat)
        self._strategy = ChangeGate(heartbeat=heartbeat)
        # The posture last written, and since when.
        self._posture: tuple[str, float] | None = None
        self._map_control = ChangeGate(heartbeat=MAP_CONTROL_HEARTBEAT)
        self._offense = ChangeGate()
        self._missions = ChangeGate()
        self._economy = ChangeGate()
        self._spawn = ChangeGate()
        self._escorts = ChangeGate()
        self._structures = ChangeGate()
        self._detection = ChangeGate()
        self._sensor_towers = ChangeGate()
        self._opening = ChangeGate(heartbeat=heartbeat)
        self._scout = ChangeGate()
        # The opening facts already written, to write only what is new.
        self._opening_facts: OpeningObservations = NO_OPENING
        self._proxy_search_written = False
        self._intel_execution = ChangeGate()
        self._perf = ChangeGate(heartbeat=heartbeat)
        self._proposals = ChangeGate()
        self._grants = ChangeGate()
        self._commands: dict[str, tuple[tuple, str]] = {}
        self._owners: dict[int, str] = {}
        self._perf_max: dict[str, float] = {}
        self._perf_frames = 0

    def started(
        self,
        *,
        time: float,
        map_view: MapView,
        race: str,
        enemy_race: str,
        opening: str | None,
        configs: Mapping[str, Any],
    ) -> None:
        self._event(
            "game.started",
            "logs",
            time,
            {
                "map": map_view.name,
                "race": race,
                "enemy_race": enemy_race,
                "opening": opening,
                "build": describe_build(),
                "config_fingerprint": fingerprint(dict(configs)),
                "configs": {
                    name: fingerprint(config) for name, config in configs.items()
                },
                "lattice": {
                    "samples": len(map_view.lattice),
                    "spacing": map_view.lattice_spacing,
                },
                "bounds": list(map_view.bounds),
            },
        )
        topology = map_view.topology
        candidates = topology.choke_candidates
        rejected = [
            candidate.reason for candidate in candidates if not candidate.accepted
        ]
        self._event(
            "map.topology_built",
            "attention",
            time,
            {
                "regions": len(topology.regions),
                "passages": len(topology.passages),
                "chokes": sum(passage.kind == "choke" for passage in topology.passages),
                "expansions": len(topology.expansion_to_region),
                "unresolved_expansions": len(map_view.expansions)
                - len(topology.expansion_to_region),
                "own_start_region": topology.own_start_region,
                "enemy_start_region": topology.enemy_start_region,
                "choke_candidates": len(candidates),
                "chokes_accepted": len(candidates) - len(rejected),
                "chokes_rejected": {
                    reason: rejected.count(reason) for reason in sorted(set(rejected))
                },
                "region_splits": {
                    split.region_id: list(split.into)
                    for split in topology.region_splits
                },
                "candidates": [
                    {
                        "position": None
                        if candidate.position is None
                        else [
                            round(float(candidate.position.x), 2),
                            round(float(candidate.position.y), 2),
                        ],
                        "regions": list(candidate.source_regions),
                        "reason": candidate.reason,
                        "passage": candidate.passage_id,
                    }
                    for candidate in candidates
                ],
            },
        )

    def ended(self, *, time: float, result: str) -> None:
        self._event("game.ended", "logs", time, {"result": result})

    def record(
        self,
        attention: AttentionState,
        awareness: AwarenessState,
        intent: StrategicIntent,
        map_control: MapControlPlan,
        offense: OffensePlan,
        proposals: Sequence[Proposal],
        economy: EconomyPlan,
        structures: StructurePlan,
        result: EngineResult,
        spawn: SpawnMode,
        micro: MicroReport,
        timings: Mapping[str, float],
        *,
        intel: IntelPlan | None = None,
        detected: DetectionReport | None = None,
        tower_building: SensorTowerReport | None = None,
        infrastructure: tuple[str, ...] = (),
        missions: Sequence[MissionView] = (),
    ) -> None:
        self._record_attention(attention)
        self._record_opening_facts(attention)
        self._record_awareness(attention.time, awareness)
        self._record_opening(attention, awareness)
        self._record_strategy(intent)
        self._record_map_control(attention.time, map_control)
        self._record_offense(attention.time, offense)
        self._record_missions(attention.time, missions)
        self._record_proposals(attention.time, proposals)
        self._record_economy(attention.time, economy)
        self._record_spawn(attention.time, spawn)
        self._record_micro(attention.time, micro)
        self._record_structures(attention.time, structures)
        if intel is not None:
            if intel.scout is not None:
                self._record_scout(attention.time, intel.scout)
            self._record_detection(attention.time, intel.detection, intel.focus)
            self._record_sensor_towers(
                attention.time,
                intel.sensor_towers,
            )
        detected = detected or DetectionReport()
        towers = tower_building or SensorTowerReport()
        signature = (infrastructure, detected.building, towers.building)
        if (
            self._intel_execution.admit(signature, now=attention.time)
            or detected.scanned_by is not None
        ):
            self._event(
                "behavior.intel_executed",
                "behaviors",
                attention.time,
                {
                    "scanned_by": detected.scanned_by,
                    "building": list(
                        infrastructure + detected.building + towers.building
                    ),
                },
            )
        self._record_grants(attention, result)
        self._record_commands(attention, awareness, intent, result)
        self._record_perf(attention.time, timings)

    def _record_opening_facts(self, attention: AttentionState) -> None:
        """Every new fact about the enemy's opening, as perception records it:
        an expansion answered, a structure counted."""

        observations = attention.enemy_opening
        previous = self._opening_facts
        if observations is previous:
            return
        self._opening_facts = observations
        now = attention.time
        for name, seen, before, position in (
            ("natural", observations.natural, previous.natural, attention.map.enemy_natural),
            ("third", observations.third, previous.third, attention.map.enemy_third),
        ):
            if seen.status is before.status:
                continue
            self._event(
                "opening_scout.expansion_checked",
                "attention",
                now,
                {
                    "expansion": name,
                    "status": seen.status.value,
                    "previous": before.status.value,
                    "position": None if position is None else _xy(position),
                    "last_checked_at": seen.last_checked_at,
                    "first_seen_at": seen.first_seen_at,
                    "absent_at": seen.absent_at,
                    # (last seen empty, first seen standing), once both happened.
                    "appeared_between": list(seen.appeared_between or ()) or None,
                },
            )
        for type_id, seen in observations.structures:
            if seen.count_seen <= previous.structure(type_id).count_seen:
                continue
            self._event(
                "opening_scout.structure_seen",
                "attention",
                now,
                {
                    "structure": type_id.name,
                    "count_seen": seen.count_seen,
                    "first_seen_at": seen.first_seen_at,
                    "last_seen_at": seen.last_seen_at,
                    "gases_seen": observations.gases_seen,
                    "workers_seen": observations.workers_seen,
                    "proxy_structures_seen": observations.proxy_structures_seen,
                    "main_coverage": observations.main_scout_coverage,
                },
            )

    def _record_opening(self, attention: AttentionState, awareness: AwarenessState) -> None:
        """How the opening reads now: the facts, the four scores and what they
        are worth."""

        observations = attention.enemy_opening
        if observations.last_updated is None:
            return
        belief = awareness.opening
        now = attention.time
        # Every new fact is written; the scores move a little every frame the
        # scout is looking at something, so they are written by band.
        signature = (
            observations.natural.status,
            observations.third.status,
            tuple((type_id.name, seen.count_seen) for type_id, seen in observations.structures),
            round(observations.main_scout_coverage, 1),
            round(belief.aggression, 1),
            round(belief.greed, 1),
            round(belief.tech, 1),
            round(belief.proxy, 1),
            round(belief.confidence, 1),
        )
        if not self._opening.admit(signature, now=now):
            return
        self._event(
            "awareness.opening_updated",
            "awareness",
            now,
            {
                "summary": _opening_summary(observations, belief, now),
                "race": belief.race.name,
                "natural": _expansion(observations.natural),
                "third": _expansion(observations.third),
                "observed": {
                    **{
                        type_id.name.lower(): seen.count_seen
                        for type_id, seen in observations.structures
                    },
                    "gases": observations.gases_seen,
                    "workers": observations.workers_seen,
                    "combat_units": observations.early_combat_units_seen,
                    "proxy_structures": observations.proxy_structures_seen,
                },
                "main_coverage": observations.main_scout_coverage,
                "last_updated": observations.last_updated,
                "belief": {
                    "aggression": belief.aggression,
                    "greed": belief.greed,
                    "tech": belief.tech,
                    "proxy": belief.proxy,
                    "confidence": belief.confidence,
                },
                "evidence": dict(belief.evidence),
            },
        )

    def _record_scout(self, now: float, scout: EarlyScoutReport) -> None:
        # Every phase of the early scout is a decision; the proxy search is
        # written the frame it is ordered.
        if scout.proxy_search and not self._proxy_search_written:
            self._proxy_search_written = True
            self._event(
                "opening_scout.proxy_search_started",
                "missions",
                now,
                {
                    "mission_id": scout.mission_id,
                    "reason": scout.reason,
                    "target": None if scout.target is None else _xy(scout.target),
                    "inputs": dict(scout.inputs),
                },
            )
        signature = (scout.mission_id, scout.phase, scout.since, scout.status)
        if not self._scout.admit(signature, now=now):
            return
        self._event(
            "opening_scout.phase_changed",
            "missions",
            now,
            {
                "mission_id": scout.mission_id,
                "phase": scout.phase,
                "previous": scout.previous,
                "since": scout.since,
                "reason": scout.reason,
                "status": scout.status,
                "target": None if scout.target is None else _xy(scout.target),
                "proxy_search": scout.proxy_search,
                "inputs": dict(scout.inputs),
            },
        )

    def _record_detection(self, now: float, detection: DetectionPlan, focus: str) -> None:
        # Every scan is a decision; the rest is state.
        # A build Ares has not started is asked again every frame: it is
        # written when what is asked changes.
        signature = (
            detection.turrets,
            detection.engineering_bay,
            detection.energy_reserve,
            detection.reason,
            focus,
        )
        changed = self._detection.admit(signature, now=now)
        acted = detection.scan is not None
        if not changed and not acted:
            return
        self._event(
            "planner.detection_planned",
            "planners",
            now,
            {
                "scan": None if detection.scan is None else _xy(detection.scan),
                "turrets": [_xy(point) for point in detection.turrets],
                "engineering_bay": detection.engineering_bay,
                "energy_reserve": detection.energy_reserve,
                "reason": detection.reason,
                "focus": focus,
                "inputs": dict(detection.inputs),
            },
        )

    def _record_sensor_towers(self, now: float, plan: SensorTowerPlan) -> None:
        signature = (plan.sites, plan.engineering_bay, plan.reason)
        if not self._sensor_towers.admit(signature, now=now):
            return
        self._event(
            "planner.sensor_towers_planned",
            "planners",
            now,
            {
                "sites": [
                    {
                        "site_id": site.site_id,
                        "base": _xy(site.base),
                        "target": _xy(site.target),
                    }
                    for site in plan.sites
                ],
                "engineering_bay": plan.engineering_bay,
                "reason": plan.reason,
                "inputs": dict(plan.inputs),
            },
        )

    def kept_clear(
        self, *, time: float, map_view: MapView, sites: Sequence[Point2], cleared: int
    ) -> None:
        self._event(
            "planner.production_kept_clear",
            "planners",
            time,
            {
                "production_sites": len(map_view.production_sites),
                "sites": [_xy(site) for site in sites],
                "cleared": cleared,
            },
        )

    def _record_structures(self, now: float, structures: StructurePlan) -> None:
        # Every relocation step is a decision.
        for event in structures.relocation:
            self._event(
                "planner.structure_relocation",
                "planners",
                now,
                {
                    "transition": event.transition,
                    "reason": event.reason,
                    "tank": event.tank,
                    "structure": event.structure,
                    "site": None if event.site is None else _xy(event.site),
                    "at": None if event.at is None else _xy(event.at),
                    "inputs": dict(event.inputs),
                },
            )
        signature = (structures.lower, structures.raise_, structures.reason)
        if not self._structures.admit(signature, now=now):
            return
        self._event(
            "planner.structures_planned",
            "planners",
            now,
            {
                "lower": list(structures.lower),
                "raise": list(structures.raise_),
                "reason": structures.reason,
                "inputs": dict(structures.inputs),
            },
        )

    def _record_attention(self, attention: AttentionState) -> None:
        army = [unit for unit in attention.own_units if is_army(unit)]
        signature = (
            len(attention.bases),
            attention.opening_done,
            bool(attention.enemy_units),
            bool(attention.radar_blips),
            len(attention.upgrades),
        )
        if not self._attention.admit(signature, now=attention.time):
            return
        self._event(
            "attention.observed",
            "attention",
            attention.time,
            {
                "minerals": attention.minerals,
                "vespene": attention.vespene,
                "supply_used": attention.supply_used,
                "supply_cap": attention.supply_cap,
                "workers": attention.workers,
                "army_units": len(army),
                "army_supply": sum(unit.supply for unit in army),
                "army_power": sum(unit.power for unit in army),
                "visible_enemy_units": len(attention.enemy_units),
                "visible_enemy_structures": len(attention.enemy_structures),
                "radar_blips": len(attention.radar_blips),
                "bases": [base.base_id for base in attention.bases],
                "opening": attention.opening,
                "opening_done": attention.opening_done,
                "upgrades": sorted(upgrade.name for upgrade in attention.upgrades),
                # Own structures by type, finished or not.
                "structures": dict(
                    sorted(
                        Counter(
                            s.type_id.name for s in attention.own_structures
                        ).items()
                    )
                ),
            },
        )

    def _record_awareness(self, now: float, awareness: AwarenessState) -> None:
        signature = (
            len(awareness.contacts),
            sum(contact.visible for contact in awareness.contacts),
            round(awareness.enemy_power),
            tuple((base.base_id, round(base.threat, 1)) for base in awareness.bases),
            # Membership, so every split and merge is written.
            tuple(
                (incident.incident_id, incident.contacts)
                for incident in awareness.incidents
            ),
            tuple(contact.tag for contact in awareness.hidden_contacts),
            awareness.cloak_seen_at,
        )
        if not self._awareness.admit(signature, now=now):
            return
        strongest = sorted(
            (contact for contact in awareness.contacts if contact.power > 0.0),
            key=lambda contact: (-contact.power * contact.confidence, contact.tag),
        )[:TOP_CONTACTS]
        self._event(
            "awareness.updated",
            "awareness",
            now,
            {
                "contacts": len(awareness.contacts),
                "visible_contacts": sum(
                    contact.visible for contact in awareness.contacts
                ),
                "enemy_power": awareness.enemy_power,
                "seen_enemy_power": awareness.seen_enemy_power,
                "expected_enemy_power": awareness.expected_enemy_power,
                "estimated_enemy_power": awareness.estimated_enemy_power,
                "enemy_uncertainty": awareness.enemy_uncertainty,
                "enemy_coverage": awareness.enemy_coverage,
                "own_power": awareness.own_power,
                "danger": awareness.danger,
                "danger_now": awareness.danger_now,
                "cloak_seen_at": awareness.cloak_seen_at,
                "hidden_contacts": [
                    contact.tag for contact in awareness.hidden_contacts
                ],
                "bases": [
                    {
                        "base_id": base.base_id,
                        "position": _xy(base.position),
                        "is_main": base.is_main,
                        "threat": base.threat,
                        "recent_threat": base.recent_threat,
                        "pressure": base.pressure,
                        "cover": base.cover,
                        "balance": base.balance,
                        "air_share": base.air_share,
                        "center": None if base.center is None else _xy(base.center),
                    }
                    for base in awareness.bases
                ],
                "incidents": [
                    {
                        "incident_id": incident.incident_id,
                        "contacts": list(incident.contacts),
                        "center": _xy(incident.center),
                        "power": incident.power,
                        "ground_power": incident.ground_power,
                        "air_power": incident.air_power,
                        "confidence": incident.confidence,
                        "threat": incident.threat,
                        "pressure_by_base": dict(incident.pressure_by_base),
                    }
                    for incident in awareness.incidents
                ],
                "strongest_contacts": [
                    {
                        "tag": contact.tag,
                        "type": contact.type_id.name,
                        "position": _xy(contact.position),
                        "power": contact.power,
                        "confidence": contact.confidence,
                        "uncertainty": contact.uncertainty,
                        "visible": contact.visible,
                        "hidden": contact.is_hidden,
                    }
                    for contact in strongest
                ],
                "field": awareness.influence.summary(),
            },
        )

    def _record_strategy(self, intent: StrategicIntent) -> None:
        posture = (intent.posture.value, intent.since)
        if posture != self._posture:
            # Why the posture changed, written once, when it changes.
            self._posture = posture
            self._event(
                "strategy.posture_changed",
                "strategy",
                intent.time,
                {
                    "posture": intent.posture.value,
                    "previous": None if intent.previous is None else intent.previous.value,
                    "reason": intent.reason,
                    "because": dict(intent.because),
                    "summary": intent.summary(),
                    "threat": intent.assessment.threat.value,
                    "emergency": intent.emergency,
                    "assessment": _assessment(intent.assessment),
                    "gates": _gates(intent),
                },
            )
        if not self._strategy.admit(
            (intent.posture, intent.since, intent.emergency), now=intent.time
        ):
            return
        self._event(
            "strategy.decided",
            "strategy",
            intent.time,
            {
                "posture": intent.posture.value,
                "previous": None if intent.previous is None else intent.previous.value,
                "since": intent.since,
                "reason": intent.reason,
                "emergency": intent.emergency,
                "defense": intent.defense,
                "army": intent.army,
                "economy": intent.economy,
                "risk": intent.risk,
                "assessment": _assessment(intent.assessment),
                "inputs": {
                    **dict(intent.assessment.inputs),
                    "army_share": intent.army_share,
                },
                "scores": dict(intent.scores),
                "gates": _gates(intent),
            },
        )

    def _record_map_control(self, now: float, plan: MapControlPlan) -> None:
        # Every choice and every switch, and a heartbeat for the field's terms;
        # the candidates only change with our bases.
        staging = plan.staging
        signature = (
            plan.source,
            plan.reason,
            _cell(plan.anchor),
            plan.fallback,
            None
            if staging is None
            else (_cell(staging.selected.position), staging.since),
        )
        if not self._map_control.admit(signature, now=now):
            return
        self._event(
            "planner.map_control_planned",
            "planners",
            now,
            {
                "anchor": _xy(plan.anchor),
                "source": plan.source,
                "reason": plan.reason,
                "posture": plan.posture.value,
                "advance": plan.advance,
                "fallback": plan.fallback,
                "passage": plan.held_passage,
                "region": plan.region,
                "staging": None if staging is None else _staging(staging),
            },
        )

    def _record_offense(self, now: float, offense: OffensePlan) -> None:
        signature = (
            offense.stage,
            offense.since,
            offense.blocked_by,
            offense.target_tag,
            None if offense.target is None else _cell(offense.target),
            offense.mission_id,
            offense.mission_status,
        )
        if not self._offense.admit(signature, now=now):
            return
        self._event(
            "planner.offense_planned",
            "planners",
            now,
            {
                "stage": offense.stage.value,
                "previous": None
                if offense.previous is None
                else offense.previous.value,
                "since": offense.since,
                "reason": offense.reason,
                "blocked_by": offense.blocked_by,
                "committed_power": offense.committed_power,
                "target": None if offense.target is None else _xy(offense.target),
                "target_tag": offense.target_tag,
                "target_kind": offense.target_kind,
                "inputs": dict(offense.inputs),
                "fight": None if offense.fight is None else _fight(offense.fight),
                "mission_id": offense.mission_id,
                "mission_status": (
                    None
                    if offense.mission_status is None
                    else offense.mission_status.value
                ),
            },
        )

    def _record_missions(self, now: float, missions: Sequence[MissionView]) -> None:
        # Opening, every phase, a cancel request and the terminal status.
        signature = tuple(
            (
                mission.mission_id,
                mission.status,
                mission.phase,
                mission.since,
                None if mission.cancel is None else mission.cancel.mode,
            )
            for mission in missions
        )
        if not self._missions.admit(signature, now=now):
            return
        self._event(
            "mission.updated",
            "missions",
            now,
            {
                "missions": [
                    {
                        "mission_id": mission.mission_id,
                        "owner": mission.owner,
                        "kind": mission.kind,
                        "status": mission.status.value,
                        "phase": mission.phase,
                        "since": mission.since,
                        "reason": mission.reason,
                        "cancel": None
                        if mission.cancel is None
                        else {
                            "mode": mission.cancel.mode.value,
                            "reason": mission.cancel.reason,
                            "time": mission.cancel.time,
                        },
                        "proposals": list(mission.proposals),
                        "granted_units": mission.granted_units,
                        "granted_power": mission.granted_power,
                    }
                    for mission in missions
                ]
            },
        )

    def _record_proposals(self, now: float, proposals: Sequence[Proposal]) -> None:
        ranked = rank(proposals)
        signature = tuple(
            (
                proposal.proposal_id,
                round(proposal.priority, 1),
                proposal.count,
                None
                if proposal.minimum_power is None
                else round(proposal.minimum_power, 1),
                proposal.must_attack,
                proposal.demand_id,
                proposal.command,
                _cell(proposal.target),
                proposal.reason,
                proposal.mission_id,
            )
            for proposal in ranked
        )
        if not self._proposals.admit(signature, now=now):
            return
        self._event(
            "planner.proposed",
            "planners",
            now,
            {
                "proposals": [
                    {
                        "proposal_id": proposal.proposal_id,
                        "owner": proposal.owner,
                        "priority": proposal.priority,
                        "command": proposal.command.value,
                        "target": _xy(proposal.target),
                        "count": proposal.count,
                        "minimum_power": proposal.minimum_power,
                        "must_attack": (
                            None
                            if proposal.must_attack is None
                            else proposal.must_attack.value
                        ),
                        "demand_id": proposal.demand_id,
                        "mission_id": proposal.mission_id,
                        "unit_types": (
                            None
                            if proposal.unit_types is None
                            else sorted(
                                unit_type.name for unit_type in proposal.unit_types
                            )
                        ),
                        "reason": proposal.reason,
                        "inputs": dict(proposal.inputs),
                    }
                    for proposal in ranked
                ]
            },
        )

    def _record_economy(self, now: float, economy: EconomyPlan) -> None:
        composition_plan = economy.composition_plan
        signature = (
            economy.active,
            economy.workers,
            economy.gas,
            economy.bases,
            economy.expand,
            economy.freeflow,
            economy.reason,
            economy.upgrades,
            economy.orbitals,
            economy.mules,
            economy.interrupt_opening,
            economy.max_production,
            economy.addons,
            economy.addons_on,
            round(economy.reactor_share, 2),
            economy.army,
            # The mix slides every frame the belief decays: a change of a
            # whole percent is news.
            tuple(
                (unit_type, round(share, 2))
                for unit_type, share, _ in economy.composition
            ),
            None
            if composition_plan is None
            else (
                composition_plan.reason,
                tuple(
                    (
                        item.enemy,
                        item.response,
                        item.status,
                        tuple(item.skipped),
                    )
                    for item in composition_plan.adaptations
                ),
                composition_plan.survival,
            ),
        )
        if not self._economy.admit(signature, now=now):
            return
        self._event(
            "planner.economy_planned",
            "planners",
            now,
            {
                "active": economy.active,
                "workers": economy.workers,
                "gas": economy.gas,
                "bases": economy.bases,
                "expand": economy.expand,
                "freeflow": economy.freeflow,
                "reason": economy.reason,
                "composition": [
                    {
                        "type": unit_type.name,
                        "proportion": proportion,
                        "priority": priority,
                    }
                    for unit_type, proportion, priority in economy.composition
                ],
                "inputs": dict(economy.inputs),
                "upgrades": [upgrade.name for upgrade in economy.upgrades],
                "orbitals": economy.orbitals,
                "mules": economy.mules,
                "interrupt_opening": economy.interrupt_opening,
                "max_production": economy.max_production,
                "addons": economy.addons,
                "addons_on": economy.addons_on.name,
                "reactor_share": economy.reactor_share,
                "army": economy.army,
                "style": economy.army
                if composition_plan is None
                else composition_plan.style,
                "baseline": []
                if composition_plan is None
                else [
                    {
                        "type": unit_type.name,
                        "proportion": proportion,
                        "priority": priority,
                    }
                    for unit_type, proportion, priority in composition_plan.baseline
                ],
                "enemy": []
                if composition_plan is None
                else [
                    {
                        "type": observed.name,
                        "canonical": canonical.name,
                        "power": power,
                    }
                    for observed, canonical, power in composition_plan.enemy
                ],
                "adaptations": []
                if composition_plan is None
                else [
                    {
                        "enemy": item.enemy.name,
                        "canonical": item.canonical.name,
                        "power": item.power,
                        "response": None
                        if item.response is None
                        else item.response.name,
                        "status": item.status,
                        "skipped": [
                            {"type": unit_type.name, "reason": reason}
                            for unit_type, reason in item.skipped
                        ],
                    }
                    for item in composition_plan.adaptations
                ],
                "survival": None
                if composition_plan is None or composition_plan.survival is None
                else {
                    "incident_id": composition_plan.survival.incident_id,
                    "added": [
                        {"type": unit_type.name, "reason": reason}
                        for unit_type, reason in composition_plan.survival.added
                    ],
                },
                "composition_reason": None
                if composition_plan is None
                else composition_plan.reason,
                "tech_ready": []
                if composition_plan is None
                else [unit_type.name for unit_type in composition_plan.tech_ready],
            },
        )

    def _record_spawn(self, now: float, spawn: SpawnMode) -> None:
        if not self._spawn.admit((spawn.freeflow, spawn.reason), now=now):
            return
        self._event(
            "behavior.spawn_executed",
            "behaviors",
            now,
            {
                "freeflow": spawn.freeflow,
                "reason": spawn.reason,
                "counts": {unit_type.name: count for unit_type, count in spawn.counts},
            },
        )

    def _record_micro(self, now: float, micro: MicroReport) -> None:
        # Every stim is a decision; which Medivacs escort is a state.
        escorts_changed = self._escorts.admit(micro.escorts, now=now)
        if not micro.stimmed and not escorts_changed:
            return
        self._event(
            "behavior.micro_executed",
            "behaviors",
            now,
            {
                "stimmed": list(micro.stimmed),
                "escorts": list(micro.escorts),
            },
        )

    def _record_grants(self, attention: AttentionState, result: EngineResult) -> None:
        owners = dict(result.owners)
        signature = tuple(
            (
                grant.proposal.proposal_id,
                grant.proposal.mission_id,
                grant.tags,
                grant.status,
            )
            for grant in result.grants
        )
        admitted = self._grants.admit(signature, now=attention.time)
        previous, self._owners = self._owners, owners
        if not admitted:
            return
        types = {unit.tag: unit.type_id.name for unit in attention.own_units}
        transfers = [
            {
                "tag": tag,
                "type": types.get(tag),
                "from": previous.get(tag),
                "to": owners.get(tag),
            }
            for tag in sorted(set(previous) | set(owners))
            if previous.get(tag) != owners.get(tag)
        ]
        self._event(
            "engine.granted",
            "engine",
            attention.time,
            {
                "grants": [
                    {
                        "proposal_id": grant.proposal.proposal_id,
                        "owner": grant.proposal.owner,
                        "mission_id": grant.proposal.mission_id,
                        "priority": grant.proposal.priority,
                        "requested": grant.proposal.count,
                        "minimum_power": grant.proposal.minimum_power,
                        "granted": len(grant.tags),
                        "granted_power": grant.power,
                        "status": grant.status.value,
                        "reason": grant.reason,
                        "tags": list(grant.tags),
                        "types": dict(
                            sorted(
                                Counter(
                                    types.get(tag, "?") for tag in grant.tags
                                ).items()
                            )
                        ),
                    }
                    for grant in result.grants
                ],
                "transfers": transfers,
                "unassigned": list(result.unassigned),
            },
        )

    def _record_commands(
        self,
        attention: AttentionState,
        awareness: AwarenessState,
        intent: StrategicIntent,
        result: EngineResult,
    ) -> None:
        """One causal record per command change: what was seen, believed and
        wanted, which proposal won, the units and the command."""

        now = attention.time
        types = {unit.tag: unit.type_id.name for unit in attention.own_units}
        live: dict[str, tuple[tuple, str]] = {}
        for grant in result.grants:
            proposal = grant.proposal
            if not grant.tags:
                continue
            signature = (
                proposal.command,
                _cell(proposal.target),
                grant.tags,
                proposal.mission_id,
            )
            live[proposal.proposal_id] = (signature, proposal.owner)
            if self._commands.get(proposal.proposal_id, (None,))[0] == signature:
                continue
            self._event(
                "engine.commanded",
                "engine",
                now,
                {
                    "proposal_id": proposal.proposal_id,
                    "owner": proposal.owner,
                    "command": proposal.command.value,
                    "target": _xy(proposal.target),
                    "tags": list(grant.tags),
                    "types": dict(
                        sorted(
                            Counter(types.get(tag, "?") for tag in grant.tags).items()
                        )
                    ),
                    "priority": proposal.priority,
                    "reason": proposal.reason,
                    "demand_id": proposal.demand_id,
                    "mission_id": proposal.mission_id,
                    "inputs": dict(proposal.inputs),
                    "strategy": {
                        "posture": intent.posture.value,
                        "reason": intent.reason,
                        "defense": intent.defense,
                        "risk": intent.risk,
                    },
                    "awareness": {
                        "danger": awareness.danger,
                        "contacts": len(awareness.contacts),
                        "enemy_power": awareness.enemy_power,
                    },
                    "attention": {
                        "army_units": sum(
                            1 for unit in attention.own_units if is_army(unit)
                        ),
                        "visible_enemy_units": len(attention.enemy_units),
                    },
                },
            )
        for proposal_id in sorted(set(self._commands) - set(live)):
            self._event(
                "engine.commanded",
                "engine",
                now,
                {
                    "proposal_id": proposal_id,
                    "owner": self._commands[proposal_id][1],
                    "command": None,
                    "target": None,
                    "tags": [],
                    "types": {},
                    "reason": "no_units_granted",
                },
            )
        self._commands = live

    def _record_perf(self, now: float, timings: Mapping[str, float]) -> None:
        self._perf_frames += 1
        for name, value in timings.items():
            self._perf_max[name] = max(self._perf_max.get(name, 0.0), float(value))
        if not self._perf.admit("frame", now=now):
            return
        self._event(
            "logs.frame_perf",
            "logs",
            now,
            {
                "frames": self._perf_frames,
                "last_ms": {
                    name: round(float(value), 3) for name, value in timings.items()
                },
                "max_ms": {
                    name: round(value, 3) for name, value in self._perf_max.items()
                },
            },
        )
        self._perf_frames = 0
        self._perf_max = {}

    def _event(
        self, name: str, component: str, time: float, data: dict[str, Any]
    ) -> None:
        self.logger.event(name, component=component, game_time=time, data=data)


def _xy(point: Point2) -> list[float]:
    return [round(float(point.x), 2), round(float(point.y), 2)]


def _expansion(observation) -> dict[str, Any]:
    return {
        "status": observation.status.value,
        "last_checked_at": observation.last_checked_at,
        "first_seen_at": observation.first_seen_at,
        "absent_at": observation.absent_at,
        "appeared_between": list(observation.appeared_between or ()) or None,
    }


def _clock(seconds: float) -> str:
    return f"{int(max(0.0, seconds)) // 60}:{int(max(0.0, seconds)) % 60:02d}"


def _opening_summary(observations, belief, now: float) -> str:
    """One line of the whole read, as the viewer and a tail of the log show it."""

    def expansion(name: str, seen) -> str:
        at = seen.first_seen_at if seen.first_seen_at is not None else seen.last_checked_at
        return f"{name}={seen.status.value}" + ("" if at is None else f"@{_clock(at)}")

    return (
        f"t={_clock(now)} race={belief.race.name} "
        f"{expansion('natural', observations.natural)} "
        f"{expansion('third', observations.third)} "
        f"coverage={observations.main_scout_coverage:.2f} | "
        f"aggression={belief.aggression:.2f} greed={belief.greed:.2f} "
        f"tech={belief.tech:.2f} proxy={belief.proxy:.2f} "
        f"confidence={belief.confidence:.2f}"
    )


def _cell(point: Point2) -> tuple[int, int]:
    return (
        int(float(point.x) // COMMAND_TARGET_CELL),
        int(float(point.y) // COMMAND_TARGET_CELL),
    )


def _assessment(assessment: GameAssessment) -> dict[str, Any]:
    return {
        "threat_level": assessment.threat_level,
        "threat": assessment.threat.value,
        "army_position": assessment.army_position,
        "economy_position": assessment.economy_position,
        "enemy_vulnerability": assessment.enemy_vulnerability,
        "power_spike": assessment.power_spike,
        "confidence": assessment.confidence,
        "setback": assessment.setback,
        "upgrade_spike": assessment.upgrade_spike,
        "supply_spike": assessment.supply_spike,
    }


def _gates(intent: StrategicIntent) -> dict[str, Any]:
    return {
        gate.posture.value: {"score": gate.score, "open": gate.open, "since": gate.since}
        for gate in intent.gates
    }


def _staging(plan: StagingPlan) -> dict[str, Any]:
    return {
        "anchor": _xy(plan.selected.position),
        "switch": plan.switch,
        "since": plan.since,
        "previous": None if plan.previous is None else _xy(plan.previous),
        "advance": plan.advance,
        "scale": plan.scale,
        "bases": plan.bases,
        "candidate_count": plan.candidate_count,
        "selected": _staging_point(plan.selected),
        "top": [_staging_point(point) for point in plan.top],
    }


def _staging_point(point: StagingPoint) -> dict[str, Any]:
    return {
        "anchor": _xy(point.position),
        "region": point.region_id,
        "passage": point.passage_id,
        "reaction": round(point.reaction, 4),
        "worst": round(point.worst, 1),
        "worst_base": point.worst_base,
        "mean": round(point.mean, 1),
        "front": round(point.front, 1),
        "choke": round(point.choke, 4),
        "threat": round(point.threat, 3),
        "support": round(point.support, 3),
        "control": round(point.control, 3),
        "exposure": round(point.exposure, 4),
        "score": round(point.score, 4),
    }


def _fight(fight: LocalFight) -> dict[str, Any]:
    return {
        "center": _xy(fight.center),
        "own_power": fight.own_power,
        "enemy_power": fight.enemy_power,
        "share": fight.share,
        "enemy_center": None if fight.enemy_center is None else _xy(fight.enemy_center),
    }

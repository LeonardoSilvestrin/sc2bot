"""The event catalog: what each layer writes to the JSONL log, and when.

State summaries go through a `ChangeGate` (on change, plus a heartbeat).
Decisions never do: every objective transition, proposal set, grant and
command change is written when it happens. ``docs/architecture.md`` lists
every event and its fields.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from sc2.position import Point2

from bot.attention import AttentionState, MapView, is_army
from bot.awareness import AwarenessState
from bot.body.engine import EngineResult, rank
from bot.ego.planners import EconomyPlan, Proposal, StructurePlan
from bot.ego.strategy import StrategyState

from .identity import describe_build, fingerprint
from .jsonl import BotLogger, ChangeGate

HEARTBEAT = 10.0
ATTENTION_HEARTBEAT = 5.0
# Coarse grid a moving target is compared on, so a drifting point is one command.
COMMAND_TARGET_CELL = 3.0
TOP_CONTACTS = 8


class Telemetry:
    def __init__(self, logger: BotLogger, *, heartbeat: float = HEARTBEAT) -> None:
        self.logger = logger
        # Resources and supply move every frame: sampled, not change-logged.
        self._attention = ChangeGate(heartbeat=ATTENTION_HEARTBEAT)
        self._awareness = ChangeGate(heartbeat=heartbeat)
        self._strategy = ChangeGate(heartbeat=heartbeat)
        self._economy = ChangeGate()
        self._structures = ChangeGate()
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
        rejected = [candidate.reason for candidate in candidates if not candidate.accepted]
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
        strategy: StrategyState,
        proposals: Sequence[Proposal],
        economy: EconomyPlan,
        structures: StructurePlan,
        result: EngineResult,
        timings: Mapping[str, float],
    ) -> None:
        self._record_attention(attention)
        self._record_awareness(attention.time, awareness)
        self._record_strategy(strategy)
        self._record_proposals(attention.time, proposals)
        self._record_economy(attention.time, economy)
        self._record_structures(attention.time, structures)
        self._record_grants(attention, result)
        self._record_commands(attention, awareness, strategy, result)
        self._record_perf(attention.time, timings)

    def _record_structures(self, now: float, structures: StructurePlan) -> None:
        if not self._structures.admit((structures.lower, structures.reason), now=now):
            return
        self._event(
            "behavior.structures_planned",
            "behaviors",
            now,
            {
                "lower": list(structures.lower),
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
                "bases": [base.base_id for base in attention.bases],
                "opening": attention.opening,
                "opening_done": attention.opening_done,
            },
        )

    def _record_awareness(self, now: float, awareness: AwarenessState) -> None:
        signature = (
            len(awareness.contacts),
            sum(contact.visible for contact in awareness.contacts),
            round(awareness.enemy_power),
            tuple((base.base_id, round(base.threat, 1)) for base in awareness.bases),
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
                "own_power": awareness.own_power,
                "danger": awareness.danger,
                "bases": [
                    {
                        "base_id": base.base_id,
                        "position": _xy(base.position),
                        "is_main": base.is_main,
                        "threat": base.threat,
                        "pressure": base.pressure,
                        "cover": base.cover,
                        "balance": base.balance,
                        "air_share": base.air_share,
                        "center": None if base.center is None else _xy(base.center),
                    }
                    for base in awareness.bases
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
                    }
                    for contact in strongest
                ],
                "field": awareness.influence.summary(),
            },
        )

    def _record_strategy(self, strategy: StrategyState) -> None:
        if not self._strategy.admit(
            (strategy.objective, strategy.since), now=strategy.time
        ):
            return
        self._event(
            "strategy.decided",
            "strategy",
            strategy.time,
            {
                "objective": strategy.objective.value,
                "previous": None
                if strategy.previous is None
                else strategy.previous.value,
                "since": strategy.since,
                "reason": strategy.reason,
                "defense": strategy.defense,
                "army": strategy.army,
                "economy": strategy.economy,
                "risk": strategy.risk,
                "rally": _xy(strategy.rally),
                "inputs": dict(strategy.inputs),
                "scores": dict(strategy.scores),
            },
        )

    def _record_proposals(self, now: float, proposals: Sequence[Proposal]) -> None:
        ranked = rank(proposals)
        signature = tuple(
            (
                proposal.proposal_id,
                round(proposal.priority, 1),
                proposal.count,
                proposal.command,
                _cell(proposal.target),
                proposal.reason,
            )
            for proposal in ranked
        )
        if not self._proposals.admit(signature, now=now):
            return
        self._event(
            "behavior.proposed",
            "behaviors",
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
        signature = (
            economy.active,
            economy.workers,
            economy.gas,
            economy.bases,
            economy.expand,
            economy.freeflow,
            economy.reason,
        )
        if not self._economy.admit(signature, now=now):
            return
        self._event(
            "behavior.economy_planned",
            "behaviors",
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
            },
        )

    def _record_grants(self, attention: AttentionState, result: EngineResult) -> None:
        owners = dict(result.owners)
        signature = tuple(
            (grant.proposal.proposal_id, grant.tags) for grant in result.grants
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
                        "priority": grant.proposal.priority,
                        "requested": grant.proposal.count,
                        "granted": len(grant.tags),
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
        strategy: StrategyState,
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
            signature = (proposal.command, _cell(proposal.target), grant.tags)
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
                    "inputs": dict(proposal.inputs),
                    "strategy": {
                        "objective": strategy.objective.value,
                        "reason": strategy.reason,
                        "defense": strategy.defense,
                        "risk": strategy.risk,
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


def _cell(point: Point2) -> tuple[int, int]:
    return (
        int(float(point.x) // COMMAND_TARGET_CELL),
        int(float(point.y) // COMMAND_TARGET_CELL),
    )

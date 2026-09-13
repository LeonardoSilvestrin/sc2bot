"""PLAN: keep a small, expendability-averse share of the army on the map.

This is the roaming counterpart to `behavior/standing/`: the core army holds
its anchor, and this claims a share of it. It only declares the squad once
the army is large enough that taking a fifth of it still leaves a real army
at home.

It asks for a role (`CombatRole.MOBILE_CONTROL`) and a share of the army's
combat supply -- never for a unit type or a head count. Every combat unit is
scored against the role, so whatever the army is made of -- Marines,
Hellions, Cyclones, or all three while production shifts -- competes for the
patrol on suitability alone, without this file changing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from sc2.position import Point2

from bot.behavior.contracts import UNRANKED_PRIORITY, BehaviorLog, MissionCandidate
from bot.engine.missions.models import MissionMode, MissionProposal, UnitRequirement
from bot.engine.missions.planning import ProposalCadence
from bot.ports.logging import BotLogger
from bot.strategy import (
    ControlObjective,
    MissionSignals,
    SpatialStrategySnapshot,
    StrategicActivity,
    StrategicContext,
)
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot
from bot.world.awareness.spatial import SpatialFieldSample

from .assessment import MapControlAssessor
from .model import (
    MapControlAssessment,
    MapControlCandidate,
    MapControlConfig,
    MapControlPlan,
)

COMPONENT = "behavior.map_control"
DEDUPLICATION_KEY = "map_control:patrol"
LatticeIndex = tuple[float, float, dict[tuple[int, int], SpatialFieldSample]]


@dataclass(slots=True)
class MapControlPlanner:
    """Declares the standing patrol squad and its share of the army."""

    config: MapControlConfig = field(default_factory=MapControlConfig)
    logger: BotLogger | None = None
    planner_id: str = "map_control_planner"
    _assessor: MapControlAssessor = field(init=False, repr=False)
    _log: BehaviorLog = field(init=False, repr=False)
    _cadence: ProposalCadence = field(
        default_factory=ProposalCadence, init=False, repr=False
    )
    last_assessment: MapControlAssessment | None = field(
        default=None, init=False, repr=False
    )
    last_plan: MapControlPlan | None = field(default=None, init=False, repr=False)
    last_candidates: tuple[MapControlCandidate, ...] = field(
        default=(), init=False, repr=False
    )

    def __post_init__(self) -> None:
        self._assessor = MapControlAssessor(config=self.config)
        self._log = BehaviorLog(component=COMPONENT, logger=self.logger)

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
        strategy: StrategicContext | None = None,
    ) -> tuple[MissionCandidate, ...]:
        now = attention.world.time
        if now < self.config.start_after:
            return ()
        if not self._cadence.ready(now, self.config.proposal_cadence):
            return ()

        assessment = self._assessor.assess(attention, awareness)
        self.last_assessment = assessment
        if assessment.combat_supply < self.config.minimum_force_supply:
            self.last_plan = None
            return ()

        self._cadence.mark(now)
        selected = self._select_anchor(
            attention, awareness, strategy or StrategicContext.neutral()
        )
        anchor = (
            attention.world.map.center if selected is None else selected.sample.position
        )
        plan = self._plan(anchor, assessment, self._signals(selected))
        self._log_plan_change(plan, assessment)
        self.last_plan = plan
        return (self._candidate_for(plan, now),)

    def _signals(self, selected: MapControlCandidate | None) -> MissionSignals:
        """The chosen anchor, read as an opportunity.

        Opportunity is its spatial score against the best a sample could
        reach; risk is the enemy threat or control standing on it; what
        patrolling there would teach us is how little we know of it.
        """

        if selected is None:
            return MissionSignals(
                activity=StrategicActivity.MAP_CONTROL,
                reason="no_spatial_field_holding_map_center",
            )
        sample = selected.sample
        return MissionSignals(
            activity=StrategicActivity.MAP_CONTROL,
            opportunity=_clamp01(selected.score / max_spatial_score(self.config)),
            risk=_clamp01(max(sample.enemy_threat, sample.enemy_control)),
            information_gain=_clamp01(selected.unknown_risk),
            control_objective=selected.objective_id,
            control_alignment=_clamp01(selected.objective_alignment),
            reason=selected.reason,
        )

    def _plan(
        self,
        anchor: Point2,
        assessment: MapControlAssessment,
        signals: MissionSignals,
    ) -> MapControlPlan:
        """Size the patrol as a share of the army's supply, not its head count.

        Units do not weigh the same -- a Cyclone is three Marines of supply
        -- so a count share would make the patrol's real size depend on
        which units the allocator happens to pick.
        """

        if self.config.desired_units is not None:
            return MapControlPlan(
                anchor=anchor,
                desired_units=self.config.desired_units,
                supply_budget=None,
                signals=signals,
            )
        return MapControlPlan(
            anchor=anchor,
            desired_units=max(1, assessment.combat_units),
            supply_budget=round(
                assessment.combat_supply * self.config.force_ratio, 2
            ),
            signals=signals,
        )

    def _select_anchor(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
        strategy: StrategicContext,
    ) -> MapControlCandidate | None:
        all_samples = awareness.spatial.candidates
        samples = tuple(
            sample
            for sample in all_samples
            if all(
                sample.position.distance_to(base.position)
                >= self.config.base_exclusion_radius
                for base in awareness.bases
            )
        )
        if not samples:
            samples = all_samples
        if not samples:
            self.last_candidates = ()
            return None

        lattice = _lattice_index(samples, awareness.spatial.sample_spacing)
        candidates = tuple(
            self._candidate(
                sample,
                _lattice_neighbours(
                    sample,
                    lattice,
                    awareness.spatial.sample_spacing,
                ),
                awareness,
                home=attention.world.map.own_start,
                strategy=strategy,
            )
            for sample in samples
        )
        frontier = tuple(
            candidate
            for candidate in candidates
            if candidate.reason == "frontier_candidate"
        )
        # If the coarse lattice has no sample in the support band, retain a
        # safe fallback instead of manufacturing a mathematically perfect
        # frontier. Dangerous points are still excluded whenever possible.
        pool = frontier or tuple(
            replace(candidate, reason="fallback_no_frontier")
            for candidate in candidates
            if candidate.sample.enemy_control < self.config.max_enemy_control
            and candidate.sample.enemy_threat < self.config.max_enemy_threat
        )
        pool = pool or candidates
        ranked_pool = tuple(sorted(pool, key=_candidate_sort_key))
        selected = ranked_pool[0]
        switch_reason = "initial_frontier_selection"
        old_candidate: MapControlCandidate | None = None

        if self.last_plan is not None:
            current_sample = awareness.spatial.at(self.last_plan.anchor)
            if (
                current_sample is not None
                and current_sample.position.distance_to(self.last_plan.anchor)
                <= awareness.spatial.sample_spacing * 1.5
                and any(
                    candidate.sample.position == current_sample.position
                    for candidate in candidates
                )
            ):
                current = self._candidate(
                    current_sample,
                    _lattice_neighbours(
                        current_sample,
                        lattice,
                        awareness.spatial.sample_spacing,
                    ),
                    awareness,
                    home=attention.world.map.own_start,
                    strategy=strategy,
                )
                old_candidate = current
                move_distance = current_sample.position.distance_to(
                    selected.sample.position
                )
                improvement = selected.score - current.score
                min_distance = (
                    self.config.retarget_min_sample_steps
                    * awareness.spatial.sample_spacing
                )
                current_valid = any(
                    candidate.sample.position == current_sample.position
                    for candidate in pool
                )
                if current_valid and (
                    move_distance < min_distance
                    or improvement < self.config.retarget_score_improvement
                ):
                    selected = current
                    switch_reason = (
                        "hysteresis_hold_nearby_anchor"
                        if move_distance < min_distance
                        else "hysteresis_hold_small_improvement"
                    )
                elif not current_valid:
                    switch_reason = _invalidation_reason(current, self.config)
                else:
                    switch_reason = "meaningful_strategic_improvement"

        ranked = tuple(sorted(candidates, key=_candidate_sort_key))
        selected = replace(selected, selected=True, reason=switch_reason)
        self.last_candidates = tuple(
            (
                selected
                if candidate.sample.position == selected.sample.position
                else candidate
            )
            for candidate in ranked
        )
        logged = list(self.last_candidates[: self.config.logged_candidate_count])
        if all(item.sample.position != selected.sample.position for item in logged):
            logged.append(selected)
        self._log.event(
            "map_control.spatial_candidates",
            now=attention.world.time,
            candidates=[candidate.log_fields() for candidate in logged],
            selected=selected.log_fields(),
        )
        if self.last_plan is None or selected.sample.position != self.last_plan.anchor:
            self._log.event(
                "map_control.anchor_changed",
                now=attention.world.time,
                old_anchor=(
                    None
                    if self.last_plan is None
                    else _xy(self.last_plan.anchor)
                ),
                new_anchor=_xy(selected.sample.position),
                old_score=(
                    None
                    if old_candidate is None
                    else round(old_candidate.score, 3)
                ),
                new_score=round(selected.score, 3),
                switch_margin=(
                    None
                    if old_candidate is None
                    else round(selected.score - old_candidate.score, 3)
                ),
                reason=switch_reason,
            )
        return selected

    def _candidate(
        self,
        sample: SpatialFieldSample,
        neighbours: tuple[SpatialFieldSample, ...],
        awareness: AwarenessSnapshot,
        *,
        home: Point2,
        strategy: StrategicContext,
    ) -> MapControlCandidate:
        spacing = max(awareness.spatial.sample_spacing, 1.0)
        support_score = _support_band(_friendly_support(sample), self.config)
        values = (
            _friendly_support(sample),
            *(_friendly_support(item) for item in neighbours),
        )
        crosses_frontier = (
            min(values) < self.config.frontier_support <= max(values)
        )
        frontier_score = 1.0 if crosses_frontier else support_score
        origins = tuple(base.position for base in awareness.bases)
        if origins:
            distance_from_support = min(
                sample.position.distance_to(origin) for origin in origins
            )
        else:
            distance_from_support = sample.position.distance_to(home)
        advancement = min(1.0, distance_from_support / (4.0 * spacing))
        travel_origin = (
            self.last_plan.anchor
            if self.last_plan is not None
            else min(
                origins,
                key=lambda origin: origin.distance_to(sample.position),
                default=home,
            )
        )
        travel_cost = min(
            1.0, sample.position.distance_to(travel_origin) / (8.0 * spacing)
        )
        unknown_risk = 1.0 - sample.knowledge_confidence
        reason = _eligibility_reason(sample, self.config)
        objective, alignment = _objective_pull(
            sample.position,
            strategy.spatial,
            spacing * self.config.objective_sigma_steps,
        )
        candidate = MapControlCandidate(
            sample=sample,
            score=0.0,
            frontier_score=frontier_score,
            advancement_score=advancement,
            support_score=support_score,
            unknown_risk=unknown_risk,
            travel_cost=travel_cost,
            information_score=strategy.intent.information * unknown_risk,
            objective_score=(
                0.0 if objective is None else objective.importance * alignment
            ),
            objective_alignment=alignment,
            objective_id=None if objective is None else objective.objective_id,
            reason=reason,
        )
        return replace(
            candidate,
            score=score_spatial_sample(sample, self.config, candidate=candidate),
        )

    def _log_plan_change(
        self, plan: MapControlPlan, assessment: MapControlAssessment
    ) -> None:
        """Only speak up when the squad's size or anchor actually moves."""

        previous = self.last_plan
        if previous is not None and (
            previous.anchor,
            previous.desired_units,
            previous.supply_budget,
        ) == (plan.anchor, plan.desired_units, plan.supply_budget):
            return
        self._log.assessed(assessment, now=assessment.now, decision="propose")
        self._log.proposed(
            plan,
            now=assessment.now,
            planner=self.planner_id,
            role=self.config.role.name,
        )

    def _candidate_for(self, plan: MapControlPlan, now: float) -> MissionCandidate:
        sequence = self._cadence.next_sequence()
        return MissionCandidate(
            draft=MissionProposal(
                proposal_id=f"{self.planner_id}:{sequence}",
                deduplication_key=DEDUPLICATION_KEY,
                planner=self.planner_id,
                kind=self.config.mission_kind,
                priority=UNRANKED_PRIORITY,
                target_key=DEDUPLICATION_KEY,
                target=plan.anchor,
                reason="persistent_map_control_share_available",
                requirement=UnitRequirement.for_role(
                    self.config.role,
                    desired=plan.desired_units,
                    # The standing mission survives full defense preemption.
                    minimum=0,
                    minimum_health=self.config.minimum_unit_health,
                    supply_budget=plan.supply_budget,
                ),
                created_at=now,
                timeout_seconds=self.config.mission_timeout,
                cooldown_seconds=self.config.failure_cooldown,
                # The core army holds most combat units, so map control must
                # be able to acquire its smaller standing share from it.
                can_preempt=True,
                commitment_seconds=self.config.commitment_seconds,
                mode=MissionMode.STANDING,
                squad_id=self.config.squad_id,
            ),
            signals=plan.signals,
        )


def max_spatial_score(config: MapControlConfig) -> float:
    """The highest score a sample could reach: every reward at full value
    and no penalty."""

    return max(
        config.friendly_weight
        + config.frontier_weight
        + config.advancement_weight
        + config.choke_weight
        + config.route_weight
        + config.information_weight
        + config.objective_weight,
        1e-6,
    )


def score_spatial_sample(
    sample: SpatialFieldSample,
    config: MapControlConfig,
    *,
    candidate: MapControlCandidate | None = None,
) -> float:
    """Frontier utility; friendly influence is a support band, not shelter."""

    support = _support_band(_friendly_support(sample), config)
    frontier = support if candidate is None else candidate.frontier_score
    advancement = 0.0 if candidate is None else candidate.advancement_score
    unknown = 1.0 - sample.knowledge_confidence
    travel = 0.0 if candidate is None else candidate.travel_cost
    information = 0.0 if candidate is None else candidate.information_score
    objective = 0.0 if candidate is None else candidate.objective_score

    return (
        config.information_weight * information
        + config.objective_weight * objective
        +
        config.friendly_weight * support
        + config.frontier_weight * frontier
        + config.advancement_weight * advancement
        + config.choke_weight * sample.choke_value
        + config.route_weight * sample.route_value
        - config.threat_weight * sample.enemy_threat
        - config.enemy_control_weight * sample.enemy_control
        - config.unknown_weight * unknown
        - config.travel_weight * travel
    )


def _support_band(value: float, config: MapControlConfig) -> float:
    return max(
        0.0,
        1.0 - abs(value - config.frontier_support) / config.frontier_support_width,
    )


def _friendly_support(sample: SpatialFieldSample) -> float:
    return (
        sample.friendly_value
        if sample.friendly_control is None
        else sample.friendly_control
    )


def _eligibility_reason(sample: SpatialFieldSample, config: MapControlConfig) -> str:
    if sample.enemy_control >= config.max_enemy_control:
        return "rejected_enemy_control"
    if sample.enemy_threat >= config.max_enemy_threat:
        return "rejected_excessive_threat"
    support = _friendly_support(sample)
    if support < config.frontier_min_support:
        return "rejected_unsupported"
    if support > config.frontier_max_support:
        return "rejected_deep_friendly_interior"
    return "frontier_candidate"


_APPROACH_ACTIVITIES = frozenset(
    {StrategicActivity.MAP_CONTROL, StrategicActivity.INFORMATION}
)


def _objective_pull(
    position: Point2, spatial: SpatialStrategySnapshot, sigma: float
) -> tuple[ControlObjective | None, float]:
    """The approach objective pulling hardest on ``position``, and its
    proximity (1 on it, fading with distance over ``sigma``).

    Only map control and information objectives: holding the ways into our
    bases is the standing army's and defense's, not the patrol's.
    """

    best: ControlObjective | None = None
    best_pull = 0.0
    best_alignment = 0.0
    sigma = max(sigma, 1e-6)
    for objective in spatial.objectives:
        if objective.activity not in _APPROACH_ACTIVITIES:
            continue
        alignment = math.exp(
            -0.5 * (position.distance_to(objective.position) / sigma) ** 2
        )
        pull = objective.importance * alignment
        if pull > best_pull:
            best, best_pull, best_alignment = objective, pull, alignment
    return best, best_alignment


def _invalidation_reason(
    candidate: MapControlCandidate, config: MapControlConfig
) -> str:
    if candidate.sample.enemy_control >= config.max_enemy_control:
        return "current_anchor_invalidated_by_enemy_control"
    if candidate.sample.enemy_threat >= config.max_enemy_threat:
        return "current_anchor_invalidated_by_enemy_threat"
    return "current_anchor_left_friendly_frontier"


def _candidate_sort_key(candidate: MapControlCandidate) -> tuple[float, float, float]:
    return (
        -candidate.score,
        float(candidate.sample.position.x),
        float(candidate.sample.position.y),
    )


def _lattice_index(
    samples: tuple[SpatialFieldSample, ...], spacing: float
) -> LatticeIndex:
    if not samples:
        return (0.0, 0.0, {})
    spacing = max(spacing, 1.0)
    min_x = min(float(sample.position.x) for sample in samples)
    min_y = min(float(sample.position.y) for sample in samples)
    return (
        min_x,
        min_y,
        {
            (
                round((float(sample.position.x) - min_x) / spacing),
                round((float(sample.position.y) - min_y) / spacing),
            ): sample
            for sample in samples
        },
    )


def _lattice_neighbours(
    sample: SpatialFieldSample,
    lattice: LatticeIndex,
    spacing: float,
) -> tuple[SpatialFieldSample, ...]:
    min_x, min_y, by_cell = lattice
    if not by_cell:
        return ()
    spacing = max(spacing, 1.0)
    cell = (
        round((float(sample.position.x) - min_x) / spacing),
        round((float(sample.position.y) - min_y) / spacing),
    )
    return tuple(
        neighbour
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        if (dx or dy)
        and (neighbour := by_cell.get((cell[0] + dx, cell[1] + dy)))
        is not None
    )


def _xy(point: Point2) -> list[float]:
    return [round(float(point.x), 1), round(float(point.y), 1)]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))

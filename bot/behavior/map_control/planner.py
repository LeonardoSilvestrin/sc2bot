"""PLAN: keep a small, expendability-averse share of the army on the map.

This is the roaming counterpart to `behavior/standing/`: the core army holds
its anchor, and this claims a share of it. It only declares the squad once
the army is large enough that taking a fifth of it still leaves a real army
at home.

It asks for the units its patrol was written for (``PATROL_UNIT_TYPES``:
Cyclones, then Hellions, then Marines and Marauders), sized as a share of the
whole army's combat supply rather than a head count. Tanks stay on the line
and Reapers and Banshees with their raids: a unit type the patrol cannot use
is never requested, whatever the army is made of.

Two decisions, each pricing its factors once (``evaluate_sample``):

- **Which anchor.** Local spatial evidence, minus caution about danger and
  unknown space, plus Strategy's value. Strategy moves the anchor only
  through that last term: ``intent.information`` pricing unknown space, and
  the importance of a control objective the point meaningfully serves
  (``ControlMatch``).
- **What the patrol is worth against other missions.** The Mission Policy's.
  It is told the anchor's local value as opportunity, and risk, information
  and the control match as separate signals -- never the selection score,
  which already contains them.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass, field, replace

from sc2.position import Point2

from bot.behavior.contracts import UNRANKED_PRIORITY, BehaviorLog, MissionCandidate
from bot.engine.missions.models import MissionMode, MissionProposal, UnitRequirement
from bot.engine.missions.planning import ProposalCadence
from bot.ports.logging import BotLogger
from bot.strategy import (
    ControlMatch,
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
        """The chosen anchor, read as an opportunity for the Mission Policy.

        Each factor reaches the policy exactly once, from the raw evidence
        rather than from the selection score:

        - opportunity: the anchor's ``local_value`` against the best a sample
          could reach -- no risk, unknown space or Strategy in it;
        - risk: the enemy threat or control standing on it;
        - information gain: how little we know of it;
        - control: the objective it meaningfully serves, if any.

        The policy then weighs those against the intent; the selection score
        that picked the anchor is never passed on.
        """

        if selected is None:
            return MissionSignals(
                activity=StrategicActivity.MAP_CONTROL,
                reason="no_spatial_field_holding_map_center",
            )
        sample = selected.sample
        return MissionSignals(
            activity=StrategicActivity.MAP_CONTROL,
            opportunity=selected.opportunity,
            risk=_clamp01(max(sample.enemy_threat, sample.enemy_control)),
            information_gain=_clamp01(selected.unknown_risk),
            control=selected.control,
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
        # The best valid alternative the selection passed over; hysteresis can
        # make the margin negative, and says so in the selected reason.
        runner_up = next(
            (
                item
                for item in ranked_pool
                if item.sample.position != selected.sample.position
            ),
            None,
        )
        rejections = Counter(
            candidate.reason
            for candidate in candidates
            if candidate.reason != "frontier_candidate"
        )
        self._log.event(
            "map_control.spatial_candidates",
            now=attention.world.time,
            candidate_count=len(candidates),
            candidate_set=candidate_set_fingerprint(samples),
            pool=(
                "frontier"
                if frontier
                else "all_candidates"
                if pool is candidates
                else "safe_fallback"
            ),
            pool_size=len(pool),
            rejections=dict(sorted(rejections.items())),
            selected=selected.log_fields(),
            runner_up=None if runner_up is None else runner_up.log_fields(),
            winning_margin=(
                None if runner_up is None else selected.score - runner_up.score
            ),
            candidates=[candidate.log_fields() for candidate in logged],
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
        origins = tuple(base.position for base in awareness.bases)
        # Held bases arrive in the game's unstable townhall order: break an
        # exact distance tie by position, never by arrival.
        travel_origin = (
            self.last_plan.anchor
            if self.last_plan is not None
            else min(
                origins,
                key=lambda origin: (
                    origin.distance_to(sample.position),
                    float(origin.x),
                    float(origin.y),
                ),
                default=home,
            )
        )
        return evaluate_sample(
            sample,
            neighbours,
            config=self.config,
            spacing=awareness.spatial.sample_spacing,
            support_origins=origins,
            home=home,
            travel_origin=travel_origin,
            strategy=strategy,
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
            unit_types=sorted(unit_type.name for unit_type in self.config.unit_types),
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
                requirement=UnitRequirement.combat(
                    unit_types=self.config.unit_types,
                    desired=plan.desired_units,
                    # The standing mission survives full defense preemption.
                    minimum=0,
                    minimum_health=self.config.minimum_unit_health,
                    type_desirability=self.config.type_desirability,
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


def evaluate_sample(
    sample: SpatialFieldSample,
    neighbours: tuple[SpatialFieldSample, ...],
    *,
    config: MapControlConfig,
    spacing: float,
    support_origins: tuple[Point2, ...],
    home: Point2,
    travel_origin: Point2,
    strategy: StrategicContext,
) -> MapControlCandidate:
    """Every term of one sample's anchor evaluation, and nothing else.

    Pure: the same inputs always give the same record. The three term groups
    and their owners are documented on ``MapControlCandidate``::

        local_value     = friendly  * support_band + frontier * frontier
                        + advance   * advancement  + choke    * choke_value
                        + route     * route_value  - travel   * travel_cost
        caution         = threat    * enemy_threat + control  * enemy_control
                        + unknown   * unknown_risk
        strategic_value = information * intent.information * unknown_risk
                        + objective   * importance * alignment   (0 without a match)
        score           = local_value - caution + strategic_value
        opportunity     = clamp01(local_value / max_local_value)
    """

    spacing = max(spacing, 1.0)
    support = _friendly_support(sample)
    support_score = _support_band(support, config)
    values = (support, *(_friendly_support(item) for item in neighbours))
    crosses_frontier = min(values) < config.frontier_support <= max(values)
    frontier_score = 1.0 if crosses_frontier else support_score
    if support_origins:
        distance_from_support = min(
            sample.position.distance_to(origin) for origin in support_origins
        )
    else:
        distance_from_support = sample.position.distance_to(home)
    advancement = min(1.0, distance_from_support / (4.0 * spacing))
    travel_cost = min(
        1.0, sample.position.distance_to(travel_origin) / (8.0 * spacing)
    )
    unknown_risk = 1.0 - sample.knowledge_confidence
    local = _local_value(
        sample,
        config,
        support_band=support_score,
        frontier=frontier_score,
        advancement=advancement,
        travel_cost=travel_cost,
    )
    pull = _control_pull(
        sample.position, strategy.spatial, spacing * config.objective_sigma_steps
    )
    control, importance = (None, 0.0) if pull is None else pull
    information_desire = strategy.intent.information
    strategic = config.information_weight * information_desire * unknown_risk + (
        0.0
        if control is None
        else config.objective_weight * importance * control.alignment
    )
    return MapControlCandidate(
        sample=sample,
        support_score=support_score,
        frontier_score=frontier_score,
        advancement_score=advancement,
        travel_cost=travel_cost,
        unknown_risk=unknown_risk,
        local_value=local,
        caution=_caution(sample, config),
        opportunity=_clamp01(local / max_local_value(config)),
        information_desire=information_desire,
        control=control,
        control_importance=importance,
        strategic_value=strategic,
        reason=_eligibility_reason(sample, config),
    )


def max_local_value(config: MapControlConfig) -> float:
    """The highest local value a sample could reach: every local reward at
    full value and no travel. Caution and Strategy are not local value."""

    return max(
        config.friendly_weight
        + config.frontier_weight
        + config.advancement_weight
        + config.choke_weight
        + config.route_weight,
        1e-6,
    )


def score_spatial_sample(
    sample: SpatialFieldSample, config: MapControlConfig
) -> float:
    """A sample's score with no neighbourhood, position or Strategy: its
    support band standing in for the frontier, minus caution.

    Frontier utility; friendly influence is a support band, not shelter.
    """

    support = _support_band(_friendly_support(sample), config)
    return _local_value(
        sample,
        config,
        support_band=support,
        frontier=support,
        advancement=0.0,
        travel_cost=0.0,
    ) - _caution(sample, config)


def _local_value(
    sample: SpatialFieldSample,
    config: MapControlConfig,
    *,
    support_band: float,
    frontier: float,
    advancement: float,
    travel_cost: float,
) -> float:
    return (
        config.friendly_weight * support_band
        + config.frontier_weight * frontier
        + config.advancement_weight * advancement
        + config.choke_weight * sample.choke_value
        + config.route_weight * sample.route_value
        - config.travel_weight * travel_cost
    )


def _caution(sample: SpatialFieldSample, config: MapControlConfig) -> float:
    return (
        config.threat_weight * sample.enemy_threat
        + config.enemy_control_weight * sample.enemy_control
        + config.unknown_weight * (1.0 - sample.knowledge_confidence)
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


def _control_pull(
    position: Point2, spatial: SpatialStrategySnapshot, sigma: float
) -> tuple[ControlMatch, float] | None:
    """The approach objective a patrol at ``position`` meaningfully serves,
    and that objective's importance; ``None`` when it serves none.

    Alignment is proximity: 1 on the objective, fading with distance over
    ``sigma``. Only a ``ControlMatch`` counts -- below
    ``MINIMUM_CONTROL_ALIGNMENT`` the kernel's tail is not an association.
    Among matches the strongest pull (importance x alignment) wins, and an
    exact tie goes to the smaller objective id, whatever order Strategy
    listed them in.

    Only map control and information objectives: holding the ways into our
    bases is the standing army's and defense's, not the patrol's.
    """

    sigma = max(sigma, 1e-6)
    best: tuple[ControlMatch, float] | None = None
    best_key: tuple[float, str] | None = None
    for objective in spatial.objectives:
        if objective.activity not in _APPROACH_ACTIVITIES:
            continue
        match = ControlMatch.from_alignment(
            objective.objective_id,
            math.exp(-0.5 * (position.distance_to(objective.position) / sigma) ** 2),
        )
        if match is None:
            continue
        key = (-objective.importance * match.alignment, objective.objective_id)
        if best_key is None or key < best_key:
            best, best_key = (match, objective.importance), key
    return best


def _invalidation_reason(
    candidate: MapControlCandidate, config: MapControlConfig
) -> str:
    if candidate.sample.enemy_control >= config.max_enemy_control:
        return "current_anchor_invalidated_by_enemy_control"
    if candidate.sample.enemy_threat >= config.max_enemy_threat:
        return "current_anchor_invalidated_by_enemy_threat"
    return "current_anchor_left_friendly_frontier"


def candidate_set_fingerprint(samples: tuple[SpatialFieldSample, ...]) -> str:
    """A short digest naming the exact sample set one selection saw.

    Order-independent and exact: every sample, with every value it carries,
    sorted by position. The same field in any order gives the same digest,
    so logs can tell two selections apart without dumping the field.
    """

    rows = sorted(
        ((float(sample.position.x), float(sample.position.y)), repr(sample))
        for sample in samples
    )
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()[:16]


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

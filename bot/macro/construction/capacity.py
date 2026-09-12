from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId

from bot.engine.economy.models import EconomicActionKind, EconomicProposal
from bot.world.attention import EconomyFacts, ProducerFacts
from bot.world.awareness import MacroPosture

from ..production.army_demand import ArmyDemand
from ..proposal_helpers import build_proposal
from ..strategy.config import MacroPlannerConfig
from ..strategy.goals import ProductionGoal


@dataclass(frozen=True, slots=True)
class CapacityAssessment:
    """Whether one production structure type is worth adding to, and why."""

    structure_type: UnitTypeId
    ready: int
    idle: int
    pending: int
    utilization: float
    desired: int
    reason: str

    @property
    def current(self) -> int:
        return self.ready + self.pending

    @property
    def demanded(self) -> bool:
        return self.desired > self.current


def assess_capacity(
    config: MacroPlannerConfig,
    economy: EconomyFacts,
    demand: ArmyDemand,
    now: float,
    *,
    minerals: float,
    vespene: float,
) -> tuple[CapacityAssessment, ...]:
    """Decide how much production infrastructure the demand justifies.

    Army debt on its own is not a reason to build: existing structures have
    to be busy first. Three floors are exempt, because none is a reaction
    to demand -- the strategy's own opening minimum, the minimum it declares
    for the number of bases taken, and the reference build's "a standard
    game has this many by now" benchmark. Everything
    above them requires a unit actually waiting on this structure type *and*
    sustained utilization of what already exists.
    """

    overflow_bonus = config.overflow.production_bonus(
        minerals=minerals, vespene=vespene
    )
    producers_in_demand = demand.producer_types_in_demand
    assessments: list[CapacityAssessment] = []
    for goal in config.goals.production:
        count = economy.structure_count(goal.structure_type)
        producer = economy.producer(goal.structure_type)
        reference_floor = (
            config.reference_build.target_for(goal.structure_type, now)
            if config.reference_build is not None
            else 0
        )
        townhall_floor = goal.minimum_for(economy.townhalls.total)
        floor = min(goal.maximum, max(townhall_floor, reference_floor))
        desired = floor
        if count.total < goal.minimum:
            reason = "production_below_opening_floor"
        elif count.total < townhall_floor:
            reason = "production_below_townhall_floor"
        elif count.total < reference_floor:
            reason = "production_below_reference_build_benchmark"
        elif (
            economy.townhalls.ready
            < goal.dynamic_growth_minimum_ready_townhalls
        ):
            reason = "dynamic_growth_waits_for_ready_townhall"
        elif goal.structure_type not in producers_in_demand:
            reason = (
                "owed_units_need_an_add_on_not_a_building"
                if goal.structure_type in demand.producer_types_needing_add_on
                else "no_unit_demand_for_this_producer"
            )
        elif not _capacity_is_saturated(goal, producer):
            reason = "existing_capacity_underutilized"
        else:
            income_target = goal.target_for_income(
                minerals=economy.mineral_collection_rate,
                vespene=economy.vespene_collection_rate,
            )
            desired = min(goal.maximum, max(floor + overflow_bonus, income_target))
            if desired <= count.total:
                reason = "saturated_capacity_still_matches_income"
            elif overflow_bonus > 0:
                reason = "saturated_capacity_and_bank_overflowing"
            else:
                reason = "sustained_income_exceeds_saturated_capacity"
        assessments.append(
            CapacityAssessment(
                structure_type=goal.structure_type,
                ready=count.ready,
                idle=producer.idle,
                pending=count.pending,
                utilization=producer.utilization_20s,
                desired=desired,
                reason=reason,
            )
        )
    return tuple(assessments)


def propose_production(
    config: MacroPlannerConfig,
    planner_id: str,
    assessments: tuple[CapacityAssessment, ...],
    posture: MacroPosture,
    now: float,
) -> tuple[EconomicProposal, ...]:
    cost = {
        goal.structure_type: goal.cost for goal in config.goals.production
    }
    return tuple(
        build_proposal(
            planner_id=planner_id,
            kind=EconomicActionKind.BUILD_PRODUCTION,
            category="production",
            target=assessment.structure_type.name,
            current_count=assessment.current,
            desired_count=assessment.desired,
            priority=config.priority_for("production", posture),
            reason=assessment.reason,
            cost=cost[assessment.structure_type],
            now=now,
        )
        for assessment in assessments
        if assessment.demanded
    )


def _capacity_is_saturated(
    goal: ProductionGoal, producer: ProducerFacts
) -> bool:
    """Sustained use, not a single frame.

    A Barracks idle for the half second between two Marines is not spare
    capacity; one idle for twenty seconds is. Both an idle structure right
    now and a low recent average veto new capacity, so a brief gap only ever
    delays growth by a tick, while genuine slack blocks it outright.
    """

    if producer.ready <= 0:
        return False
    if producer.idle > 0:
        return False
    return producer.utilization_20s >= goal.minimum_utilization

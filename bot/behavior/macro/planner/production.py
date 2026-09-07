from __future__ import annotations

from bot.behavior.macro.config import MacroPlannerConfig
from bot.behavior.macro.goals import ProductionGoal
from bot.behavior.macro.planner.common import build_proposal
from bot.behavior.posture import MacroPosture
from bot.engine.economy.models import EconomicActionKind, EconomicProposal
from bot.world.observation.models import EconomyFacts, ProducerFacts


def propose_production(
    config: MacroPlannerConfig,
    planner_id: str,
    economy: EconomyFacts,
    posture: MacroPosture,
    now: float,
    *,
    minerals: float,
    vespene: float,
) -> tuple[EconomicProposal, ...]:
    proposals: list[EconomicProposal] = []
    overflow_bonus = config.overflow.production_bonus(
        minerals=minerals, vespene=vespene
    )
    for goal in config.goals.production:
        count = economy.structure_count(goal.structure_type)
        income_target = goal.target_for_income(
            minerals=economy.mineral_collection_rate,
            vespene=economy.vespene_collection_rate,
        )
        if income_target > goal.minimum and not _production_is_saturated(
            goal,
            economy.producer(goal.structure_type),
        ):
            income_target = goal.minimum
        reference_floor = (
            config.reference_build.target_for(goal.structure_type, now)
            if config.reference_build is not None
            else 0
        )
        base_desired = max(goal.minimum, income_target, reference_floor)
        desired = min(goal.maximum, base_desired + overflow_bonus)
        if count.total >= desired:
            continue
        if count.total < goal.minimum:
            reason = "production_below_opening_floor"
        elif count.total < reference_floor:
            reason = "production_below_reference_build_benchmark"
        elif desired > base_desired:
            reason = "resource_bank_overflowing"
        else:
            reason = "sustained_income_exceeds_busy_production_capacity"
        proposals.append(
            build_proposal(
                planner_id=planner_id,
                kind=EconomicActionKind.BUILD_PRODUCTION,
                category="production",
                target=goal.structure_type.name,
                target_count=desired,
                priority=config.priority_for("production", posture),
                reason=reason,
                cost=goal.cost,
                now=now,
            )
        )
    return tuple(proposals)


def _production_is_saturated(goal: ProductionGoal, producer: ProducerFacts) -> bool:
    if producer.ready <= 0:
        # Missing producer telemetry must not make a valid high-income
        # signal disappear. Runtime snapshots normally have this detail.
        return True
    return producer.busy / producer.ready >= goal.minimum_utilization

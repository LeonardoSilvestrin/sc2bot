from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId

from bot.behavior.macro.config import MacroPlannerConfig
from bot.behavior.macro.planner.common import build_proposal
from bot.behavior.posture import MacroPosture
from bot.engine.economy.models import EconomicActionKind, EconomicProposal
from bot.world.observation.models import EconomyFacts


def propose_gas(
    config: MacroPlannerConfig,
    planner_id: str,
    economy: EconomyFacts,
    posture: MacroPosture,
    now: float,
) -> EconomicProposal | None:
    goals = config.goals
    refinery_count = economy.structure_count(UnitTypeId.REFINERY)
    desired = min(
        goals.max_refineries,
        economy.townhalls.ready * goals.refineries_per_townhall,
    )
    if desired <= 0 or refinery_count.total >= desired:
        return None
    # Do not take workers off minerals for all gases at the start of a base.
    minimum_workers = max(12, (desired - 1) * 3)
    if economy.workers.total < minimum_workers:
        return None
    return build_proposal(
        planner_id=planner_id,
        kind=EconomicActionKind.BUILD_GAS,
        category="gas",
        target=UnitTypeId.REFINERY.name,
        target_count=desired,
        priority=config.priority_for("gas", posture),
        reason="refinery_count_below_strategy_target",
        cost=config.gas_cost,
        now=now,
    )

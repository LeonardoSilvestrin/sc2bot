from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId

from bot.behavior.macro.config import MacroPlannerConfig
from bot.behavior.macro.planner.common import build_proposal
from bot.behavior.posture import MacroPosture
from bot.engine.economy.models import EconomicActionKind, EconomicProposal
from bot.world.observation.models import EconomyFacts


def propose_supply(
    config: MacroPlannerConfig,
    planner_id: str,
    economy: EconomyFacts,
    supply_used: float,
    supply_cap: float,
    posture: MacroPosture,
    now: float,
) -> EconomicProposal | None:
    if supply_cap >= config.max_supply_cap:
        return None
    effective_remaining = supply_cap + economy.supply_pending - supply_used
    if effective_remaining > config.supply_buffer:
        return None
    return build_proposal(
        planner_id=planner_id,
        kind=EconomicActionKind.PRODUCE_SUPPLY,
        category="supply",
        target=UnitTypeId.SUPPLYDEPOT.name,
        target_count=None,
        priority=config.priority_for("supply", posture),
        reason="effective_supply_capacity_near_limit",
        cost=config.supply_cost,
        now=now,
    )

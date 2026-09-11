from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId

from bot.engine.economy.models import EconomicActionKind, EconomicProposal
from bot.world.attention import EconomyFacts
from bot.world.awareness import MacroPosture

from ..proposal_helpers import build_proposal
from ..strategy.config import MacroPlannerConfig


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
    # Counting depots (rather than leaving the count open) lets the observer
    # confirm this action the moment the next one is under way, instead of
    # holding the supply slot until its confirmation timeout expires.
    current = economy.structure_count(UnitTypeId.SUPPLYDEPOT).total
    return build_proposal(
        planner_id=planner_id,
        kind=EconomicActionKind.PRODUCE_SUPPLY,
        category="supply",
        target=UnitTypeId.SUPPLYDEPOT.name,
        current_count=current,
        desired_count=current + 1,
        priority=config.priority_for("supply", posture),
        reason="effective_supply_capacity_near_limit",
        cost=config.supply_cost,
        now=now,
    )

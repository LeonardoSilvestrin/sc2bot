from __future__ import annotations

from math import ceil

from sc2.ids.unit_typeid import UnitTypeId

from bot.engine.economy.models import EconomicActionKind, EconomicProposal
from bot.world.attention import EconomyFacts
from bot.world.awareness import MacroPosture

from ..proposal_helpers import build_proposal, saturation_target
from ..strategy.config import MacroPlannerConfig

_SATURATION_THRESHOLD: dict[MacroPosture, float] = {
    MacroPosture.BALANCED: 0.90,
    MacroPosture.GREED: 0.72,
    MacroPosture.RECOVERY: 1.00,
    MacroPosture.DEFENSE: 1.00,
}


def propose_expansion(
    config: MacroPlannerConfig,
    planner_id: str,
    economy: EconomyFacts,
    posture: MacroPosture,
    now: float,
) -> EconomicProposal | None:
    goals = config.goals
    if economy.townhalls.total >= goals.max_townhalls:
        return None
    # One command center already in progress represents this exact goal.
    if economy.townhalls.pending > 0:
        return None
    if posture is MacroPosture.DEFENSE:
        return None

    target = saturation_target(economy, goals.workers_per_townhall)
    threshold = _SATURATION_THRESHOLD[posture]
    if target > 0 and economy.workers.total < ceil(target * threshold):
        return None
    return build_proposal(
        planner_id=planner_id,
        kind=EconomicActionKind.EXPAND,
        category="expansion",
        target=UnitTypeId.COMMANDCENTER.name,
        current_count=economy.townhalls.total,
        desired_count=economy.townhalls.total + 1,
        priority=config.priority_for("expansion", posture),
        reason=f"current_bases_saturated_for_{posture.name.lower()}_posture",
        cost=config.expansion_cost,
        now=now,
    )

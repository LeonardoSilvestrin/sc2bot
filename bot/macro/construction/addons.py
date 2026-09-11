from __future__ import annotations

from bot.engine.economy.models import EconomicActionKind, EconomicProposal
from bot.world.attention import EconomyFacts
from bot.world.awareness import MacroPosture

from ..proposal_helpers import build_proposal
from ..strategy.config import MacroPlannerConfig


def propose_addons(
    config: MacroPlannerConfig,
    planner_id: str,
    economy: EconomyFacts,
    posture: MacroPosture,
    now: float,
) -> tuple[EconomicProposal, ...]:
    proposals: list[EconomicProposal] = []
    for addon, desired, cost in config.goals.addons:
        current = economy.structure_count(addon).total
        if desired <= 0 or current >= desired:
            continue
        proposals.append(
            build_proposal(
                planner_id=planner_id,
                kind=EconomicActionKind.BUILD_ADDON,
                category="addon",
                target=addon.name,
                current_count=current,
                desired_count=desired,
                priority=config.priority_for("addon", posture),
                reason="addon_count_below_strategy_target",
                cost=cost,
                now=now,
            )
        )
    return tuple(proposals)

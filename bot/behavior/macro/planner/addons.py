from __future__ import annotations

from bot.behavior.macro.config import MacroPlannerConfig
from bot.behavior.macro.planner.common import build_proposal
from bot.behavior.posture import MacroPosture
from bot.engine.economy.models import EconomicActionKind, EconomicProposal
from bot.world.observation.models import EconomyFacts


def propose_addons(
    config: MacroPlannerConfig,
    planner_id: str,
    economy: EconomyFacts,
    posture: MacroPosture,
    now: float,
) -> tuple[EconomicProposal, ...]:
    proposals: list[EconomicProposal] = []
    for addon, desired, cost in config.goals.addons:
        if desired <= 0 or economy.structure_count(addon).total >= desired:
            continue
        proposals.append(
            build_proposal(
                planner_id=planner_id,
                kind=EconomicActionKind.BUILD_ADDON,
                category="addon",
                target=addon.name,
                target_count=desired,
                priority=config.priority_for("addon", posture),
                reason="addon_count_below_strategy_target",
                cost=cost,
                now=now,
            )
        )
    return tuple(proposals)

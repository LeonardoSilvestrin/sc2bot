from __future__ import annotations

from math import ceil

from bot.engine.economy.models import EconomicActionKind, EconomicProposal
from bot.world.knowledge import MacroPosture
from bot.world.observation import EconomyFacts

from ..macro_config import MacroPlannerConfig
from .proposal_helpers import build_proposal


def propose_army(
    config: MacroPlannerConfig,
    planner_id: str,
    economy: EconomyFacts,
    posture: MacroPosture,
    now: float,
    *,
    minerals: float,
    vespene: float,
) -> tuple[EconomicProposal, ...]:
    goals = config.goals
    counts = {
        goal.unit_type: economy.unit_count(goal.unit_type).total for goal in goals.army
    }
    army_supply = sum(counts[goal.unit_type] * goal.cost.supply for goal in goals.army)
    # A bank overflowing above the configured thresholds is evidence the
    # standard army_supply_target is not absorbing income fast enough;
    # raise the ceiling instead of sitting on the pile until a fight forces
    # it to be spent.
    overflow_supply_bonus = config.overflow.army_supply_bonus(
        minerals=minerals, vespene=vespene
    )
    if army_supply >= goals.army_supply_target + overflow_supply_bonus:
        return ()

    total_weight = sum(goal.weight for goal in goals.army)
    # Anchor the ratio to whichever member is furthest behind its own
    # weight share, not to the grand total: an over-built member (eg. spare
    # Marines) must never inflate every other member's target just because
    # the army as a whole is already large. The lookahead only widens the
    # shared target while some member is still below its configured floor;
    # once every member has cleared its own minimum, a member already
    # sitting at its bottleneck-implied share must not be re-proposed to
    # chase the remaining army-supply gap.
    bottleneck_scale = min(counts[goal.unit_type] / goal.weight for goal in goals.army)
    below_own_minimum = any(
        counts[goal.unit_type] < goal.minimum for goal in goals.army
    )
    desired_total = bottleneck_scale * total_weight
    if below_own_minimum:
        desired_total += goals.composition_lookahead
    if overflow_supply_bonus > 0.0:
        cheapest_supply = min(goal.cost.supply for goal in goals.army)
        if cheapest_supply > 0.0:
            desired_total += overflow_supply_bonus / cheapest_supply
    proposals: list[EconomicProposal] = []
    for goal in goals.army:
        ratio_target = ceil(desired_total * goal.weight / total_weight)
        desired = max(goal.minimum, ratio_target)
        if counts[goal.unit_type] >= desired:
            continue
        proposals.append(
            build_proposal(
                planner_id=planner_id,
                kind=EconomicActionKind.PRODUCE_UNIT,
                category="army",
                target=goal.unit_type.name,
                target_count=desired,
                priority=config.priority_for(
                    "army", posture, offset=goal.priority_offset
                ),
                reason="unit_count_below_strategy_composition",
                cost=goal.cost,
                now=now,
            )
        )
    return tuple(proposals)

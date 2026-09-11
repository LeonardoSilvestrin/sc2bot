from __future__ import annotations

from bot.engine.economy.models import EconomicActionKind, EconomicProposal, ResourceCost
from bot.world.attention import EconomyFacts


def saturation_target(economy: EconomyFacts, workers_per_townhall: int) -> int:
    """The worker count the current bases can usefully absorb.

    Ares already tracks ``ideal_harvesters`` once bases/geysers are scouted;
    ``workers_per_townhall`` is only a fallback for the handful of frames
    before that becomes available.
    """

    if economy.ideal_harvesters > 0:
        return economy.ideal_harvesters
    return economy.townhalls.ready * workers_per_townhall


def build_proposal(
    *,
    planner_id: str,
    kind: EconomicActionKind,
    category: str,
    target: str,
    current_count: int,
    desired_count: int,
    priority: int,
    reason: str,
    cost: ResourceCost,
    now: float,
) -> EconomicProposal:
    """Argue for *one* step from ``current_count`` towards ``desired_count``.

    A goal ("we want five Barracks") is not a purchase. Callers pass both
    numbers and get an action worth exactly one item, so the ``cost`` the
    economy controller reserves is the cost of what the action will really
    do. Whether the remaining gap is still worth closing is re-decided next
    tick, against the world as it is by then.
    """

    deduplication_key = f"{planner_id}:{category}:{target.lower()}"
    return EconomicProposal(
        proposal_id=deduplication_key,
        planner=planner_id,
        kind=kind,
        priority=priority,
        reason=reason,
        cost=cost,
        created_at=now,
        deduplication_key=deduplication_key,
        target=target,
        target_count=min(desired_count, max(0, current_count) + 1),
    )

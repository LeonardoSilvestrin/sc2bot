from __future__ import annotations

from bot.engine.economy.models import EconomicActionKind, EconomicProposal, ResourceCost
from bot.world.observation.models import EconomyFacts


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
    target_count: int | None,
    priority: int,
    reason: str,
    cost: ResourceCost,
    now: float,
) -> EconomicProposal:
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
        target_count=target_count,
    )

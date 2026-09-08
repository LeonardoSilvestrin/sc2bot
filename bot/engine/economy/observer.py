from __future__ import annotations

from collections.abc import Iterable

from sc2.ids.unit_typeid import UnitTypeId

from bot.engine.economy.models import (
    EconomicActionSnapshot,
    EconomicActionStatus,
    EconomicFeedback,
    EconomicFeedbackKind,
)
from bot.world.attention import EconomyFacts


def observe_economic_confirmations(
    snapshots: Iterable[EconomicActionSnapshot],
    economy: EconomyFacts,
) -> tuple[EconomicFeedback, ...]:
    """Confirm commands once Attention exposes their target or pending item."""

    feedback: list[EconomicFeedback] = []
    for snapshot in snapshots:
        if snapshot.status not in {
            EconomicActionStatus.PENDING,
            EconomicActionStatus.IN_FLIGHT,
        }:
            continue
        proposal = snapshot.proposal
        if proposal.target_count is None:
            continue
        observed = _observed_total(snapshot, economy)
        if observed is None or observed < proposal.target_count:
            continue
        feedback.append(
            EconomicFeedback(
                action_id=snapshot.action_id,
                kind=EconomicFeedbackKind.CONFIRMED,
                reason="target_observed_in_attention",
            )
        )
    return tuple(feedback)


def merge_economic_feedback(
    observed: Iterable[EconomicFeedback],
    dispatched: Iterable[EconomicFeedback],
) -> tuple[EconomicFeedback, ...]:
    """Prefer observed game truth over adapter feedback for the same action."""

    observed_items = tuple(observed)
    observed_ids = {item.action_id for item in observed_items}
    return observed_items + tuple(
        item for item in dispatched if item.action_id not in observed_ids
    )


def _observed_total(
    snapshot: EconomicActionSnapshot,
    economy: EconomyFacts,
) -> int | None:
    proposal = snapshot.proposal
    kind = proposal.kind

    # Importing here avoids a circular import in the public contracts module.
    from bot.engine.economy.models import EconomicActionKind

    if kind is EconomicActionKind.PRODUCE_WORKER:
        return economy.workers.total
    if kind is EconomicActionKind.EXPAND:
        return economy.townhalls.total

    if proposal.target is None:
        return None
    try:
        target = UnitTypeId[proposal.target]
    except KeyError:
        return None

    if kind is EconomicActionKind.PRODUCE_UNIT:
        return economy.unit_count(target).total
    if kind in {
        EconomicActionKind.PRODUCE_SUPPLY,
        EconomicActionKind.BUILD_GAS,
        EconomicActionKind.BUILD_PRODUCTION,
        EconomicActionKind.BUILD_ADDON,
    }:
        return economy.structure_count(target).total
    return None

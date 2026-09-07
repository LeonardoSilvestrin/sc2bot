from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId

from bot.engine.economy import merge_economic_feedback, observe_economic_confirmations
from bot.engine.economy.models import (
    EconomicAction,
    EconomicActionKind,
    EconomicActionSnapshot,
    EconomicActionStatus,
    EconomicFeedback,
    EconomicFeedbackKind,
    EconomicProposal,
    ResourceCost,
)
from bot.world.observation.models import CountFacts, EconomyFacts, UnitTypeCount


def snapshot(
    kind: EconomicActionKind,
    *,
    target: str | None,
    target_count: int,
) -> EconomicActionSnapshot:
    proposal = EconomicProposal(
        proposal_id="proposal",
        planner="macro",
        kind=kind,
        priority=50,
        reason="test",
        cost=ResourceCost(),
        created_at=1.0,
        target=target,
        target_count=target_count,
    )
    action = EconomicAction("action", proposal, admitted_at=1.0)
    return EconomicActionSnapshot(
        action=action,
        status=EconomicActionStatus.PENDING,
        reason="waiting",
        dispatched_at=None,
        finished_at=None,
    )


class EconomyObserverTests(unittest.TestCase):
    def test_confirms_worker_as_soon_as_pending_count_reaches_target(self):
        action = snapshot(
            EconomicActionKind.PRODUCE_WORKER,
            target="SCV",
            target_count=17,
        )
        economy = EconomyFacts(workers=CountFacts(existing=16, ready=16, pending=1))

        feedback = observe_economic_confirmations((action,), economy)

        self.assertEqual(len(feedback), 1)
        self.assertEqual(feedback[0].kind, EconomicFeedbackKind.CONFIRMED)

    def test_confirms_structure_using_ready_plus_pending(self):
        action = snapshot(
            EconomicActionKind.BUILD_PRODUCTION,
            target="BARRACKS",
            target_count=4,
        )
        economy = EconomyFacts(
            structure_counts=(
                UnitTypeCount(UnitTypeId.BARRACKS, existing=4, ready=3, pending=1),
            )
        )

        self.assertEqual(
            len(observe_economic_confirmations((action,), economy)),
            1,
        )

    def test_observed_confirmation_wins_over_dispatch_feedback(self):
        observed = EconomicFeedback(
            "action",
            EconomicFeedbackKind.CONFIRMED,
            "observed",
        )
        dispatched = EconomicFeedback(
            "action",
            EconomicFeedbackKind.DISPATCHED,
            "accepted",
        )

        self.assertEqual(
            merge_economic_feedback((observed,), (dispatched,)),
            (observed,),
        )


if __name__ == "__main__":
    unittest.main()

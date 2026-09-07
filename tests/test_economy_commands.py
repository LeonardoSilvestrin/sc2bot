from __future__ import annotations

import unittest
from unittest.mock import patch

from bot.adapters.ares.economy_commands import AresEconomyCommands
from bot.engine.economy.models import (
    EconomicAction,
    EconomicActionKind,
    EconomicFeedbackKind,
    EconomicProposal,
    ResourceCost,
)


def make_action(action_id: str = "economic-action-0001") -> EconomicAction:
    proposal = EconomicProposal(
        proposal_id="worker",
        planner="test",
        kind=EconomicActionKind.PRODUCE_WORKER,
        priority=50,
        reason="test",
        cost=ResourceCost(minerals=50, supply=1.0),
        created_at=1.0,
        target="SCV",
    )
    return EconomicAction(action_id=action_id, proposal=proposal, admitted_at=1.0)


class AresEconomyCommandsDispatchTests(unittest.TestCase):
    """Ares macro behaviors are meant to be retried every frame; a call that

    does nothing this frame (no idle producer yet) must not be mistaken for a
    real failure, or the runtime's per-tick retry loop would kill the
    commitment on its very first quiet frame.
    """

    def test_no_progress_this_frame_returns_none_not_a_failure(self):
        commands = AresEconomyCommands(bot=object())

        with patch.object(AresEconomyCommands, "_execute", return_value=False):
            self.assertIsNone(commands.dispatch(make_action()))

    def test_progress_this_frame_returns_dispatched(self):
        commands = AresEconomyCommands(bot=object())

        with patch.object(AresEconomyCommands, "_execute", return_value=True):
            feedback = commands.dispatch(make_action())

        self.assertEqual(feedback.kind, EconomicFeedbackKind.DISPATCHED)
        self.assertEqual(feedback.reason, "ares_command_accepted")

    def test_an_exception_is_a_real_failure(self):
        commands = AresEconomyCommands(bot=object())

        with patch.object(
            AresEconomyCommands, "_execute", side_effect=RuntimeError("boom")
        ):
            feedback = commands.dispatch(make_action())

        self.assertEqual(feedback.kind, EconomicFeedbackKind.FAILED)
        self.assertIn("ares_dispatch_error", feedback.reason)


if __name__ == "__main__":
    unittest.main()

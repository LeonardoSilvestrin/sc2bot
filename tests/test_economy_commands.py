from __future__ import annotations

import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import patch

from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.ids.unit_typeid import UnitTypeId

from bot.adapters.ares.economy_commands import AresEconomyCommands
from bot.engine.economy.models import (
    EconomicAction,
    EconomicActionKind,
    EconomicFeedbackKind,
    EconomicProposal,
    ResourceCost,
)


def make_action(
    action_id: str = "economic-action-0001",
    *,
    kind: EconomicActionKind = EconomicActionKind.PRODUCE_WORKER,
    target: str = "SCV",
) -> EconomicAction:
    proposal = EconomicProposal(
        proposal_id=target.lower(),
        planner="test",
        kind=kind,
        priority=50,
        reason="test",
        cost=ResourceCost(minerals=50, supply=1.0),
        created_at=1.0,
        target=target,
    )
    return EconomicAction(action_id=action_id, proposal=proposal, admitted_at=1.0)


class AresEconomyCommandsDispatchTests(unittest.TestCase):
    """Ares macro behaviors are meant to be retried every frame; a call that

    does nothing this frame (no idle producer yet) must not be mistaken for a
    real failure, or the runtime's per-tick retry loop would kill the
    commitment on its very first quiet frame.
    """

    def test_no_progress_this_frame_is_acknowledged_as_waiting(self):
        commands = AresEconomyCommands(bot=object())

        with patch.object(AresEconomyCommands, "_execute", return_value=False):
            feedback = commands.dispatch(make_action())

        self.assertEqual(feedback.kind, EconomicFeedbackKind.WAITING)
        self.assertEqual(feedback.reason, "ares_no_progress_this_frame")

    def test_accepted_construction_step_returns_dispatched(self):
        commands = AresEconomyCommands(bot=object())
        depot = make_action(
            kind=EconomicActionKind.PRODUCE_SUPPLY, target="SUPPLYDEPOT"
        )

        with patch.object(AresEconomyCommands, "_execute", return_value=True):
            feedback = commands.dispatch(depot)

        self.assertEqual(feedback.kind, EconomicFeedbackKind.DISPATCHED)
        self.assertEqual(feedback.reason, "ares_command_accepted")

    def test_issued_train_order_is_confirmed_rather_than_left_in_flight(self):
        # In flight, a train waited for Attention to count `target_count`; a
        # unit of that type dying first made that unreachable and blocked the
        # whole type until the confirmation timeout.
        commands = AresEconomyCommands(bot=object())

        for action in (
            make_action(),
            make_action(kind=EconomicActionKind.PRODUCE_UNIT, target="MARINE"),
        ):
            with self.subTest(kind=action.proposal.kind.name):
                with patch.object(
                    AresEconomyCommands, "_execute", return_value=True
                ):
                    feedback = commands.dispatch(action)

                self.assertEqual(feedback.kind, EconomicFeedbackKind.CONFIRMED)
                self.assertEqual(feedback.reason, "ares_train_order_issued")

    def test_quiet_spawn_explains_that_its_producer_is_busy(self):
        structures = defaultdict(tuple)
        for producer_type in UNIT_TRAINED_FROM[UnitTypeId.SCV]:
            structures[producer_type] = (SimpleNamespace(is_ready=True),)
        bot = SimpleNamespace(
            minerals=50,
            vespene=0,
            supply_left=10.0,
            worker_type=UnitTypeId.SCV,
            tech_ready_for_unit=lambda _unit_type: True,
            mediator=SimpleNamespace(get_own_structures_dict=structures),
        )
        commands = AresEconomyCommands(bot=bot)

        with patch.object(AresEconomyCommands, "_execute", return_value=False):
            feedback = commands.dispatch(make_action())

        self.assertEqual(feedback.kind, EconomicFeedbackKind.WAITING)
        self.assertEqual(feedback.reason, "compatible_producer_busy")

    def test_quiet_dispatch_explains_when_reserved_minerals_are_gone(self):
        bot = SimpleNamespace(minerals=0, vespene=0, supply_left=10.0)
        commands = AresEconomyCommands(bot=bot)

        with patch.object(AresEconomyCommands, "_execute", return_value=False):
            feedback = commands.dispatch(make_action())

        self.assertEqual(feedback.kind, EconomicFeedbackKind.WAITING)
        self.assertEqual(feedback.reason, "minerals_unavailable_at_dispatch")

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

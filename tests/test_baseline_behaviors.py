from __future__ import annotations

import unittest
from unittest.mock import Mock

from bot.adapters.ares.depot_toggle import DepotToggle
from bot.adapters.ares.frame import register_baseline_behaviors


class RegisterBaselineBehaviorsTests(unittest.TestCase):
    def test_registers_mining_and_depot_toggle_every_call(self):
        bot = Mock()

        register_baseline_behaviors(bot)

        registered_types = [
            type(call.args[0]) for call in bot.register_behavior.call_args_list
        ]
        self.assertIn(DepotToggle, registered_types)
        self.assertEqual(bot.register_behavior.call_count, 2)

    def test_is_a_no_op_when_the_bot_cannot_register_behaviors(self):
        bot = object()

        register_baseline_behaviors(bot)  # must not raise


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId

from bot.behavior.macro import MacroPlannerConfig, macro_config_for_opening


class MacroConfigForOpeningTests(unittest.TestCase):
    def test_bio_three_one_one_opening_resolves_the_bio_profile(self):
        config = macro_config_for_opening("BioThreeOneOne")

        self.assertEqual(config.goals.opening_name, "BioThreeOneOne")

    def test_banshee_cloak_opening_resolves_the_banshee_profile(self):
        config = macro_config_for_opening("BansheeCloak")

        self.assertEqual(config.goals.opening_name, "BansheeCloak")
        self.assertIn(
            UnitTypeId.BANSHEE, {goal.unit_type for goal in config.goals.army}
        )

    def test_unknown_or_unresolved_opening_falls_back_to_the_default_profile(self):
        default = MacroPlannerConfig()

        self.assertEqual(
            macro_config_for_opening("SomeFutureBuild").goals.opening_name,
            default.goals.opening_name,
        )
        self.assertEqual(
            macro_config_for_opening("").goals.opening_name,
            default.goals.opening_name,
        )


if __name__ == "__main__":
    unittest.main()

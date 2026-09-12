from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.macro import MacroPlanner, MacroPlannerConfig, macro_config_for_opening
from bot.world.attention import AttentionSnapshot, EconomyFacts, MapFacts, WorldFacts
from bot.world.awareness import AwarenessService


def opening_attention(opening_name: str, *, now: float = 5.0) -> AttentionSnapshot:
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=12.0,
            supply_cap=15.0,
            own_units=(),
            enemy_units=(),
            map=MapFacts(
                center=Point2((50, 50)),
                own_start=Point2((10, 10)),
                enemy_starts=(Point2((90, 90)),),
            ),
            economy=EconomyFacts(opening_name=opening_name),
        )
    )


def propose(planner: MacroPlanner, attention: AttentionSnapshot) -> None:
    planner.propose(attention, AwarenessService().update(attention))


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

    def test_battle_mech_opening_resolves_the_mech_profile(self):
        config = macro_config_for_opening("BattleMech")

        self.assertEqual(config.goals.opening_name, "BattleMech")
        self.assertIsNone(config.reference_build)

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


class FollowOpeningTests(unittest.TestCase):
    """Picking this game's profile is macro's job, not the runtime's."""

    def test_a_following_planner_adopts_the_opening_once_it_is_known(self):
        planner = MacroPlanner(follow_opening=True)

        propose(planner, opening_attention(""))
        self.assertEqual(planner.config.goals.opening_name, "BioThreeOneOne")

        propose(planner, opening_attention("BansheeCloak", now=6.0))
        self.assertEqual(planner.config.goals.opening_name, "BansheeCloak")

    def test_the_first_known_opening_is_locked_in(self):
        planner = MacroPlanner(follow_opening=True)

        propose(planner, opening_attention("BansheeCloak"))
        propose(planner, opening_attention("BioThreeOneOne", now=6.0))

        self.assertEqual(planner.config.goals.opening_name, "BansheeCloak")

    def test_a_pinned_config_never_follows(self):
        planner = MacroPlanner(config=MacroPlannerConfig())

        propose(planner, opening_attention("BansheeCloak"))

        self.assertEqual(planner.config.goals.opening_name, "BioThreeOneOne")


if __name__ == "__main__":
    unittest.main()

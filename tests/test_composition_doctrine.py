"""Doctrine is production intent: macro buys within it, missions never see it."""

from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from sc2.ids.unit_typeid import UnitTypeId

from bot.macro import (
    BIO,
    MECH,
    CompositionDoctrine,
    banshee_cloak,
    bio_three_one_one,
)
from tests.test_behavior_architecture import imported_modules

DOCTRINE = Path(__file__).parents[1] / "bot" / "macro" / "composition" / "doctrine.py"


class DoctrineTests(unittest.TestCase):
    def test_mech_is_built_around_hellions_cyclones_and_tanks(self):
        self.assertEqual(
            MECH.core,
            frozenset({UnitTypeId.HELLION, UnitTypeId.CYCLONE, UnitTypeId.SIEGETANK}),
        )
        self.assertEqual(
            MECH.support, frozenset({UnitTypeId.VIKINGFIGHTER, UnitTypeId.THOR})
        )
        self.assertIn(UnitTypeId.BANSHEE, MECH.specialized)

    def test_bio_and_mech_share_the_siege_tank_as_core(self):
        self.assertIn(UnitTypeId.SIEGETANK, BIO.core)
        self.assertIn(UnitTypeId.SIEGETANK, MECH.core)
        self.assertNotIn(UnitTypeId.MARINE, MECH.unit_types)

    def test_a_unit_type_belongs_to_one_tier_and_a_doctrine_needs_a_core(self):
        with self.assertRaises(ValueError):
            CompositionDoctrine(
                name="broken",
                core=frozenset({UnitTypeId.MARINE}),
                support=frozenset({UnitTypeId.MARINE}),
            )
        with self.assertRaises(ValueError):
            CompositionDoctrine(name="empty", core=frozenset())

    def test_a_doctrine_is_plain_production_intent(self):
        """No capabilities, no roles, no preference for the allocator."""

        self.assertEqual(
            {name for name in imported_modules(DOCTRINE) if name.startswith("bot")},
            set(),
        )
        for attribute in ("tools_for", "preferred_unit_types", "generic_unit_types"):
            with self.subTest(attribute=attribute):
                self.assertFalse(hasattr(BIO, attribute))


class GoalSetDoctrineTests(unittest.TestCase):
    def test_every_current_goal_set_buys_within_bio(self):
        for profile in (bio_three_one_one, banshee_cloak):
            goals = profile()
            with self.subTest(goals=goals.name):
                self.assertIs(goals.doctrine, BIO)
                for goal in goals.army:
                    self.assertTrue(goals.doctrine.includes(goal.unit_type))

    def test_a_goal_set_cannot_buy_outside_its_doctrine(self):
        with self.assertRaisesRegex(ValueError, "outside the mech doctrine: MARAUDER"):
            replace(bio_three_one_one(), doctrine=MECH)


if __name__ == "__main__":
    unittest.main()

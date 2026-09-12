"""The shared domain: unit profiles, suitability, and the roles scored on it."""

from __future__ import annotations

import unittest
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId

from bot.domain import (
    COMBAT_UNIT_TYPES,
    UNIT_PROFILES,
    Capability,
    CapabilityRequirement,
    CombatCapabilities,
    capabilities_for,
    is_combat_unit,
    score_unit_for_requirement,
)
from bot.engine.missions import CombatRole


def score(unit_type: UnitTypeId, role: CombatRole) -> float:
    return score_unit_for_requirement(unit_type, role.requirement).score


class CapabilityProfileTests(unittest.TestCase):
    def test_every_persistent_force_and_battlemech_unit_has_a_profile(self):
        for unit_type in (
            UnitTypeId.MARINE,
            UnitTypeId.MARAUDER,
            UnitTypeId.REAPER,
            UnitTypeId.HELLION,
            UnitTypeId.CYCLONE,
            UnitTypeId.SIEGETANK,
            UnitTypeId.THOR,
            UnitTypeId.VIKINGFIGHTER,
            UnitTypeId.BANSHEE,
        ):
            with self.subTest(unit_type=unit_type.name):
                self.assertIsNotNone(capabilities_for(unit_type))

    def test_a_unit_without_a_combat_profile_is_never_admitted(self):
        self.assertIsNone(capabilities_for(UnitTypeId.SCV))
        suitability = score_unit_for_requirement(
            UnitTypeId.MEDIVAC, CombatRole.MOBILE_CONTROL.requirement
        )
        self.assertFalse(suitability.admitted)
        self.assertEqual(suitability.rejection, "no_capability_profile")

    def test_combat_units_are_the_profiled_units_that_can_attack(self):
        self.assertEqual(COMBAT_UNIT_TYPES, frozenset(UNIT_PROFILES))
        for unit_type in (
            UnitTypeId.MARINE,
            UnitTypeId.HELLION,
            UnitTypeId.CYCLONE,
            UnitTypeId.SIEGETANKSIEGED,
            UnitTypeId.THOR,
            UnitTypeId.VIKINGFIGHTER,
            UnitTypeId.BANSHEE,
        ):
            with self.subTest(unit_type=unit_type.name):
                self.assertTrue(is_combat_unit(unit_type))
        for unit_type in (UnitTypeId.SCV, UnitTypeId.MEDIVAC, UnitTypeId.RAVEN):
            with self.subTest(unit_type=unit_type.name):
                self.assertFalse(is_combat_unit(unit_type))

    def test_a_sieged_tank_is_still_the_tank_its_mission_was_given(self):
        self.assertIs(
            capabilities_for(UnitTypeId.SIEGETANKSIEGED),
            capabilities_for(UnitTypeId.SIEGETANK),
        )

    def test_weapon_domains_stay_physical_facts(self):
        viking = UNIT_PROFILES[UnitTypeId.VIKINGFIGHTER]
        hellion = UNIT_PROFILES[UnitTypeId.HELLION]
        self.assertFalse(viking.attacks_ground)
        self.assertTrue(viking.is_flying)
        self.assertFalse(hellion.attacks_air)
        for unit_type, profile in UNIT_PROFILES.items():
            with self.subTest(unit_type=unit_type.name):
                self.assertEqual(profile.anti_air > 0.0, profile.attacks_air)

    def test_a_scalar_that_contradicts_its_weapon_domain_is_rejected(self):
        with self.assertRaises(ValueError):
            CombatCapabilities(
                mobility=0.5,
                anti_ground=0.0,
                anti_air=0.6,
                range=0.5,
                siege=0.0,
                splash=0.0,
                durability=0.5,
                attacks_ground=True,
                attacks_air=False,
            )
        with self.assertRaises(ValueError):
            CombatCapabilities(
                mobility=1.5,
                anti_ground=0.5,
                anti_air=0.0,
                range=0.5,
                siege=0.0,
                splash=0.0,
                durability=0.5,
                attacks_ground=True,
                attacks_air=False,
            )


def profile(**overrides) -> CombatCapabilities:
    values: dict[str, Any] = {
        "mobility": 0.0,
        "anti_ground": 0.0,
        "anti_air": 0.0,
        "range": 0.0,
        "siege": 0.0,
        "splash": 0.0,
        "durability": 0.0,
        "attacks_ground": True,
        "attacks_air": False,
    }
    values.update(overrides)
    return CombatCapabilities(**values)


class SuitabilityTests(unittest.TestCase):
    def test_coverage_is_the_normalized_weighted_mean_and_floors_are_quadratic(self):
        requirement = CapabilityRequirement(
            name="test",
            mobility=3.0,
            anti_ground=1.0,
            floors=((Capability.MOBILITY, 0.8),),
        )

        suitability = requirement.assess(profile(mobility=0.4, anti_ground=1.0))

        # (3 * 0.4 + 1 * 1.0) / 4
        self.assertAlmostEqual(suitability.coverage, 0.55)
        # half of the mobility floor costs three quarters of the score
        self.assertAlmostEqual(suitability.floor_factor, 0.25)
        self.assertAlmostEqual(suitability.score, 0.1375)
        self.assertAlmostEqual(requirement.assess(profile(mobility=0.4)).score, 0.075)

    def test_meeting_every_floor_costs_nothing(self):
        requirement = CapabilityRequirement(
            name="test", mobility=1.0, floors=((Capability.MOBILITY, 0.5),)
        )

        self.assertAlmostEqual(requirement.assess(profile(mobility=0.9)).score, 0.9)

    def test_there_is_no_cut_off_a_poor_fit_scores_low_not_zero(self):
        requirement = CapabilityRequirement(
            name="test", mobility=1.0, floors=((Capability.MOBILITY, 0.5),)
        )

        poor = requirement.assess(profile(mobility=0.1))

        self.assertTrue(poor.admitted)
        self.assertAlmostEqual(poor.score, 0.1 * 0.2**2)

    def test_lacking_a_floored_capability_outright_scores_zero_and_says_why(self):
        requirement = CapabilityRequirement(
            name="test",
            mobility=1.0,
            siege=1.0,
            floors=((Capability.SIEGE, 0.5),),
        )

        suitability = requirement.assess(profile(mobility=1.0))

        self.assertGreater(suitability.coverage, 0.0)
        self.assertEqual(suitability.score, 0.0)
        self.assertEqual(suitability.rejection, "lacks_siege")

    def test_a_hard_constraint_is_not_bought_back_by_other_capabilities(self):
        """A mission that must shoot air gets nothing from a fast Hellion."""

        requirement = CapabilityRequirement(
            name="anti_air_patrol",
            mobility=1.0,
            anti_air=0.1,
            requires_anti_air=True,
        )

        suitability = requirement.assess(UNIT_PROFILES[UnitTypeId.HELLION])

        self.assertGreater(suitability.coverage, 0.8)
        self.assertEqual(suitability.score, 0.0)
        self.assertFalse(suitability.admitted)
        self.assertEqual(suitability.rejection, "cannot_attack_air")
        self.assertTrue(requirement.assess(UNIT_PROFILES[UnitTypeId.MARINE]).admitted)

    def test_a_requirement_needs_a_positive_weight_and_sane_floors(self):
        with self.assertRaises(ValueError):
            CapabilityRequirement(name="empty")
        with self.assertRaises(ValueError):
            CapabilityRequirement(name="negative", mobility=-1.0, range=1.0)
        with self.assertRaises(ValueError):
            CapabilityRequirement(
                name="floor", mobility=1.0, floors=((Capability.MOBILITY, 0.0),)
            )


class RoleTests(unittest.TestCase):
    def test_mobile_control_ranks_mobile_units_first_and_the_tank_near_last(self):
        role = CombatRole.MOBILE_CONTROL

        cyclone = score(UnitTypeId.CYCLONE, role)
        hellion = score(UnitTypeId.HELLION, role)
        marine = score(UnitTypeId.MARINE, role)
        tank = score(UnitTypeId.SIEGETANK, role)
        self.assertGreater(cyclone, hellion)
        self.assertGreater(hellion, marine)
        self.assertGreater(marine, 2 * tank)
        self.assertGreater(tank, 0.0)
        self.assertEqual(
            score_unit_for_requirement(UnitTypeId.VIKINGFIGHTER, role.requirement)
            .rejection,
            "cannot_attack_ground",
        )

    def test_the_siege_tank_is_the_natural_siege_anchor(self):
        role = CombatRole.SIEGE_ANCHOR

        self.assertGreater(score(UnitTypeId.SIEGETANK, role), 0.8)
        for unit_type in (UnitTypeId.HELLION, UnitTypeId.MARINE, UnitTypeId.CYCLONE):
            with self.subTest(unit_type=unit_type.name):
                self.assertEqual(
                    score_unit_for_requirement(unit_type, role.requirement).rejection,
                    "lacks_siege",
                )

    def test_the_tank_is_worth_more_as_an_anchor_than_as_mobile_control(self):
        self.assertGreater(
            score(UnitTypeId.SIEGETANK, CombatRole.SIEGE_ANCHOR),
            score(UnitTypeId.SIEGETANK, CombatRole.MOBILE_CONTROL),
        )


if __name__ == "__main__":
    unittest.main()

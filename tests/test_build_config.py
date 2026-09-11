from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId


class TerranBuildConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parents[1] / "terran_builds.yml"
        cls.config = yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_all_matchups_select_an_existing_build(self):
        builds = self.config["Builds"]
        for matchup in ("Protoss", "Terran", "Zerg", "Random"):
            for name in self.config["BuildChoices"][matchup]["Cycle"]:
                self.assertIn(name, builds)

    def test_ladder_data_persistence_is_disabled(self):
        self.assertIs(self.config["UseData"], False)

    def test_commands_use_names_understood_by_ares(self):
        special = {"supply", "worker_scout", "orbital", "gas", "expand"}
        invalid: list[str] = []
        for name, build in self.config["Builds"].items():
            for step in build["OpeningBuildOrder"]:
                command = step.split()[1].lower()
                if command in special:
                    continue
                if (
                    command.upper() not in UnitTypeId.__members__
                    and command.upper() not in UpgradeId.__members__
                ):
                    invalid.append(f"{name}: {command}")
        self.assertEqual(invalid, [])

    def test_opening_does_not_bypass_the_mission_scout(self):
        for name, build in self.config["Builds"].items():
            commands = build["OpeningBuildOrder"]
            self.assertFalse(
                any("worker_scout" in step.lower() for step in commands),
                msg=f"{name} should not issue its own scout",
            )

    def test_banshee_cloak_build_is_available_for_every_matchup_and_test(self):
        for matchup in ("Protoss", "Terran", "Zerg", "Random", "test_123"):
            self.assertIn("BansheeCloak", self.config["BuildChoices"][matchup]["Cycle"])

    def test_banshee_cloak_uses_two_tech_lab_starports_and_banshee_speed(self):
        commands = self.config["Builds"]["BansheeCloak"]["OpeningBuildOrder"]

        self.assertTrue(any("starport *2" in step.lower() for step in commands))
        self.assertTrue(any("starporttechlab *2" in step.lower() for step in commands))
        self.assertTrue(any("bansheecloak" in step.lower() for step in commands))
        self.assertTrue(any("bansheespeed" in step.lower() for step in commands))

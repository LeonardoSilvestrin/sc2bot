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
        commands = self.config["Builds"]["BioThreeOneOne"]["OpeningBuildOrder"]
        invalid: list[str] = []
        for step in commands:
            command = step.split()[1].lower()
            if command in special:
                continue
            if command.upper() not in UnitTypeId.__members__ and command.upper() not in UpgradeId.__members__:
                invalid.append(command)
        self.assertEqual(invalid, [])

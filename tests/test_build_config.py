from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from ares.consts import BuildOrderOptions
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
        special = set(BuildOrderOptions.__members__)
        invalid: list[str] = []
        for name, build in self.config["Builds"].items():
            for step in build["OpeningBuildOrder"]:
                tokens = step.split("@")[0].split()
                command = tokens[1].upper()
                if command == BuildOrderOptions.ADDONSWAP.name:
                    invalid.extend(
                        f"{name}: {token}"
                        for token in tokens[2:]
                        if token.upper() not in UnitTypeId.__members__
                    )
                    continue
                if command in special:
                    continue
                if (
                    command not in UnitTypeId.__members__
                    and command not in UpgradeId.__members__
                ):
                    invalid.append(f"{name}: {command.lower()}")
        self.assertEqual(invalid, [])

    def test_opening_does_not_bypass_the_mission_scout(self):
        for name, build in self.config["Builds"].items():
            commands = build["OpeningBuildOrder"]
            self.assertFalse(
                any("worker_scout" in step.lower() for step in commands),
                msg=f"{name} should not issue its own scout",
            )

    def test_every_matchup_and_test_is_forced_to_battle_mech(self):
        for matchup in ("Protoss", "Terran", "Zerg", "Random", "test_123"):
            self.assertEqual(
                self.config["BuildChoices"][matchup]["Cycle"], ["BattleMech"]
            )

    def test_battle_mech_factory_takes_the_barracks_reactor_for_hellions(self):
        commands = [
            step.lower() for step in self.config["Builds"]["BattleMech"]["OpeningBuildOrder"]
        ]

        def index(fragment: str) -> int:
            return next(i for i, step in enumerate(commands) if fragment in step)

        reactor = index("barracksreactor")
        swap = index("addonswap factory barracksreactor")
        hellions = index("hellion *4")
        self.assertLess(reactor, swap)
        self.assertLess(swap, hellions)
        self.assertLess(index("starporttechlab"), index(" banshee"))
        # The second Starport and the extra Factories follow the third base,
        # which macro decides -- the opening builds one of each.
        self.assertEqual(
            sum(step.split()[1] in {"factory", "starport"} for step in commands), 2
        )
        self.assertFalse(any("*2" in step for step in commands))

    def test_banshee_cloak_uses_two_tech_lab_starports_and_banshee_speed(self):
        commands = self.config["Builds"]["BansheeCloak"]["OpeningBuildOrder"]

        self.assertTrue(any("starport *2" in step.lower() for step in commands))
        self.assertTrue(any("starporttechlab *2" in step.lower() for step in commands))
        self.assertTrue(any("bansheecloak" in step.lower() for step in commands))
        self.assertTrue(any("bansheespeed" in step.lower() for step in commands))

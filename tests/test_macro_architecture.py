"""The boundary between behavior and macro.

Behaviors govern units already on the map, through missions, squads and unit
leases. Macro governs what to spend on -- minerals, gas, supply, production,
tech and bases -- through the economy controller. Both read the same
Attention and Awareness. These are the tests that fail when one starts
reaching into the other.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from sc2.position import Point2

from bot.engine.economy import EconomicProposal
from bot.macro import MacroPlanner, SpendPlanner
from bot.world.attention import AttentionSnapshot, MapFacts, WorldFacts
from bot.world.awareness import AwarenessService
from tests.test_behavior_architecture import imported_modules

BOT = Path(__file__).parents[1] / "bot"


def forbidden_imports(package: Path, prefixes: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for path in sorted(package.rglob("*.py")):
        for name in sorted(imported_modules(path)):
            if any(
                name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes
            ):
                found.append(f"{path.relative_to(BOT).as_posix()}: {name}")
    return found


class MacroBoundaryTests(unittest.TestCase):
    def test_macro_is_not_a_behavior(self):
        self.assertEqual(list((BOT / "behavior" / "macro").rglob("*.py")), [])

    def test_macro_never_reaches_for_units_missions_or_squads(self):
        """No mission, squad or lease vocabulary on the spend side -- and no
        Ares: executing a purchase is the economy adapter's job."""

        self.assertEqual(
            forbidden_imports(
                BOT / "macro",
                (
                    "ares",
                    "bot.adapters",
                    "bot.app",
                    "bot.behavior",
                    "bot.engine.missions",
                    "bot.engine.squads",
                ),
            ),
            [],
        )

    def test_behaviors_never_decide_spending(self):
        """A behavior may read what exists; what to buy is macro's call."""

        self.assertEqual(
            forbidden_imports(BOT / "behavior", ("bot.engine.economy", "bot.macro")),
            [],
        )

    def test_neither_engine_knows_the_macro_domain(self):
        self.assertEqual(forbidden_imports(BOT / "engine", ("bot.macro",)), [])

    def test_the_economy_controller_owns_no_unit(self):
        self.assertEqual(
            forbidden_imports(
                BOT / "engine" / "economy",
                ("bot.engine.missions", "bot.engine.squads"),
            ),
            [],
        )


class SpendContractTests(unittest.TestCase):
    def test_the_macro_planner_proposes_purchases_not_missions(self):
        attention = AttentionSnapshot(
            WorldFacts(
                iteration=30,
                time=30.0,
                minerals=400,
                vespene=0,
                # Close to the cap, so at least a supply depot is argued for.
                supply_used=14.0,
                supply_cap=15.0,
                own_units=(),
                enemy_units=(),
                map=MapFacts(
                    center=Point2((50, 50)),
                    own_start=Point2((10, 10)),
                    enemy_starts=(Point2((90, 90)),),
                ),
            )
        )
        planner = MacroPlanner()

        proposals = planner.propose(attention, AwarenessService().update(attention))

        self.assertIsInstance(planner, SpendPlanner)
        self.assertTrue(proposals)
        for proposal in proposals:
            self.assertIsInstance(proposal, EconomicProposal)


if __name__ == "__main__":
    unittest.main()

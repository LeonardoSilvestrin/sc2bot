"""One decision pipeline, and the boundaries that keep it one.

    Awareness -> Strategy -> Behavior planners -> Mission Policy
              -> MissionController / UnitAllocator -> Executors

Planners describe opportunities, only the Mission Policy prices them, and
the engine arbitrates a final number without knowing where it came from.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

BOT = Path(__file__).resolve().parents[1] / "bot"
# The objective names that cannot be mistaken for another vocabulary
# (`CombatPosture.PRESSURE` and "recover" are not Strategy's).
OBJECTIVE_NAMES = ("STABILIZE", "BUILD_ADVANTAGE", "TAKE_MAP_CONTROL")
STRATEGIC_CONCEPTS = (
    "StrategicObjective",
    "StrategicIntent",
    "StrategicActivity",
    "StrategicContext",
    "MissionSignals",
    "ControlObjective",
)


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))


def imported_modules(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def relative(path: Path) -> str:
    return path.relative_to(BOT).as_posix()


def calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    ]


class PriorityOwnershipTests(unittest.TestCase):
    """Final mission priority must not creep back into planners."""

    def test_no_behavior_type_declares_a_priority_field(self):
        found = [
            f"{relative(path)}: {node.target.id}"
            for path in sorted((BOT / "behavior").rglob("*.py"))
            for cls in ast.walk(parse(path))
            if isinstance(cls, ast.ClassDef)
            for node in cls.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and "priority" in node.target.id.lower()
        ]

        self.assertEqual(found, [])

    def test_every_behavior_proposal_is_drafted_unranked(self):
        drafted: list[str] = []
        ranked: list[str] = []
        for path in sorted((BOT / "behavior").rglob("*.py")):
            for call in calls_named(parse(path), "MissionProposal"):
                value = next(
                    (item.value for item in call.keywords if item.arg == "priority"),
                    None,
                )
                if isinstance(value, ast.Name) and value.id == "UNRANKED_PRIORITY":
                    drafted.append(relative(path))
                else:
                    ranked.append(f"{relative(path)}:{call.lineno}")

        self.assertEqual(ranked, [])
        self.assertEqual(
            sorted(set(drafted)),
            [
                "behavior/defense/planner.py",
                "behavior/harass/banshee/planner.py",
                "behavior/harass/reaper/planner.py",
                "behavior/map_control/planner.py",
                "behavior/scouting/planner.py",
                "behavior/standing/planner.py",
            ],
        )

    def test_only_the_mission_ranker_prices_candidates(self):
        pricers = [
            relative(path)
            for path in sorted(BOT.rglob("*.py"))
            if "strategy" not in path.relative_to(BOT).parts[:1]
            and re.search(
                r"\b(score_mission|to_priority)\b",
                path.read_text(encoding="utf-8-sig"),
            )
        ]

        self.assertEqual(pricers, ["app/mission_ranking.py"])


class AwarenessDescriptiveTests(unittest.TestCase):
    """Awareness says where control exists, never where it is wanted."""

    def test_awareness_types_carry_no_prescription(self):
        prescriptive = re.compile(r"desired|importance|priority|objective|intent")
        found = [
            f"{relative(path)}: {cls.name}.{node.target.id}"
            for path in sorted((BOT / "world" / "awareness").rglob("*.py"))
            for cls in ast.walk(parse(path))
            if isinstance(cls, ast.ClassDef)
            for node in cls.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and prescriptive.search(node.target.id.lower())
        ]

        self.assertEqual(found, [])

    def test_awareness_never_imports_strategy(self):
        found = [
            relative(path)
            for path in sorted((BOT / "world").rglob("*.py"))
            if any(name.startswith("bot.strategy") for name in imported_modules(path))
        ]

        self.assertEqual(found, [])


class EngineBlindnessTests(unittest.TestCase):
    """The engine receives a number and a requirement, nothing strategic."""

    def test_the_engine_never_imports_strategy_or_behavior(self):
        found = [
            f"{relative(path)}: {name}"
            for path in sorted((BOT / "engine").rglob("*.py"))
            for name in sorted(imported_modules(path))
            if name.startswith(("bot.strategy", "bot.behavior", "bot.app"))
        ]

        self.assertEqual(found, [])

    def test_the_engine_never_names_a_strategic_concept(self):
        found = [
            f"{relative(path)}: {word}"
            for path in sorted((BOT / "engine").rglob("*.py"))
            for word in (*STRATEGIC_CONCEPTS, *OBJECTIVE_NAMES)
            if re.search(rf"\b{word}\b", path.read_text(encoding="utf-8-sig"))
        ]

        self.assertEqual(found, [])


class BehaviorInterpretationTests(unittest.TestCase):
    """Behaviors read Strategy's intent, never its objective."""

    def test_behaviors_never_read_the_strategic_objective(self):
        found = [
            relative(path)
            for path in sorted((BOT / "behavior").rglob("*.py"))
            if re.search(
                r"\b(StrategicObjective|StrategySnapshot|StrategicDirector"
                r"|derive_intent|IntentConfig)\b",
                path.read_text(encoding="utf-8-sig"),
            )
        ]

        self.assertEqual(found, [])

    def test_behaviors_only_import_strategy_contracts(self):
        allowed = {
            "bot.strategy",
            "bot.strategy.MissionSignals",
            "bot.strategy.StrategicActivity",
            "bot.strategy.StrategicContext",
            "bot.strategy.ControlObjective",
            "bot.strategy.ControlTargetKind",
            # Legacy transport still read by Standing and Map Control until
            # they consume the spatial objectives.
            "bot.strategy.MacroPosture",
        }
        found = [
            f"{relative(path)}: {name}"
            for path in sorted((BOT / "behavior").rglob("*.py"))
            for name in sorted(imported_modules(path))
            if name.startswith("bot.strategy") and name not in allowed
        ]

        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()

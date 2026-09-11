"""The rules the behavior layer is supposed to keep.

These are the tests that fail when the structure erodes: an assessment that
starts reading mission state, a behavior planner that starts commanding
units, or a `MissionController` that starts knowing what a Banshee is.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app.mission_registry import DEFAULT_EXECUTOR_FACTORIES
from bot.behavior.contracts import (
    BehaviorAssessment,
    BehaviorAssessor,
    BehaviorPlanner,
)
from bot.behavior.defense import DefenseAssessor, DefensePlanner
from bot.behavior.harass.banshee import BansheeHarassAssessor, BansheeHarassPlanner
from bot.behavior.harass.reaper import ReaperHarassAssessor, ReaperHarassPlanner
from bot.behavior.map_control import MapControlAssessor, MapControlPlanner
from bot.behavior.scouting import IntelAssessor, IntelPlanner
from bot.behavior.standing import StandingAssessor, StandingPlanner
from bot.engine.missions import MissionKind, UnitRequirement
from bot.world.attention import (
    AttentionSnapshot,
    MapFacts,
    MapObservation,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness import AwarenessService

BOT = Path(__file__).parents[1] / "bot"
MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
    observations=(MapObservation("enemy_natural", Point2((80, 80)), True),),
)


def world_snapshot(now: float) -> AttentionSnapshot:
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=0.0,
            supply_cap=0.0,
            own_units=(banshee(1), tank(2)),
            enemy_units=(),
            map=MAP,
        )
    )

ASSESSORS = (
    BansheeHarassAssessor(),
    ReaperHarassAssessor(),
    StandingAssessor(),
    DefenseAssessor(),
    MapControlAssessor(),
    IntelAssessor(),
)
PLANNERS = (
    BansheeHarassPlanner(),
    ReaperHarassPlanner(),
    StandingPlanner(),
    DefensePlanner(),
    MapControlPlanner(),
    IntelPlanner(),
)

# Every behavior is a vertical folder. Spend decisions are not a behavior at
# all -- they live in `bot/macro`, whose boundary `test_macro_architecture.py`
# keeps.
VERTICAL_BEHAVIORS = (
    ("harass", "banshee"),
    ("harass", "reaper"),
    ("standing",),
    ("defense",),
    ("map_control",),
    ("scouting",),
)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def banshee(tag: int, *, health: float = 1.0) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.BANSHEE,
        position=Point2((10, 10)),
        health_percentage=health,
        is_flying=True,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
    )


def tank(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.SIEGETANK,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
    )


class BehaviorShapeTests(unittest.TestCase):
    def test_every_migrated_behavior_has_an_assessor_and_a_planner(self):
        for assessor in ASSESSORS:
            self.assertIsInstance(assessor, BehaviorAssessor)
        for planner in PLANNERS:
            self.assertIsInstance(planner, BehaviorPlanner)
            self.assertTrue(planner.planner_id.strip())

    def test_a_vertical_behavior_folder_holds_its_whole_pipeline(self):
        for parts in VERTICAL_BEHAVIORS:
            folder = BOT.joinpath("behavior", *parts)
            present = {path.name for path in folder.glob("*.py")}
            self.assertEqual(
                present,
                {
                    "__init__.py",
                    "model.py",
                    "assessment.py",
                    "planner.py",
                    "executor.py",
                },
                "/".join(parts),
            )


class AssessmentIndependenceTests(unittest.TestCase):
    def test_assessment_modules_never_reach_for_mission_or_engine_state(self):
        """Assessment reads the world, not the bot's own commitments."""

        violations: list[str] = []
        for path in BOT.glob("behavior/**/assessment.py"):
            for name in imported_modules(path):
                if name.startswith("bot.engine") or name.startswith("bot.app"):
                    violations.append(f"{path.parent.name}/{path.name}: {name}")
        self.assertEqual(violations, [])

    def test_an_assessment_is_a_reading_and_carries_no_mission_state(self):
        service = AwarenessService()
        current = world_snapshot(20.0)
        awareness = service.update(current)

        for assessor in ASSESSORS:
            assessment = assessor.assess(current, awareness)
            with self.subTest(assessor=type(assessor).__name__):
                self.assertIsInstance(assessment, BehaviorAssessment)
                self.assertIsInstance(assessment.log_fields(), dict)
                for forbidden in ("mission_id", "assigned_units", "status", "owner"):
                    self.assertFalse(
                        hasattr(assessment, forbidden),
                        f"{type(assessment).__name__}.{forbidden}",
                    )


class MissionControllerGenericityTests(unittest.TestCase):
    def test_the_controller_never_imports_a_behavior(self):
        for path in (BOT / "engine").rglob("*.py"):
            for name in imported_modules(path):
                self.assertFalse(
                    name.startswith("bot.behavior"),
                    f"{path.name} imports {name}",
                )

    def test_adding_a_behavior_only_touches_the_executor_registry(self):
        """A new mission kind is registered, not special-cased.

        `MissionController` is handed the whole kind -> executor table and
        looks kinds up in it; nothing in the controller enumerates them.
        """

        controller_source = (BOT / "engine" / "missions" / "controller.py").read_text(
            encoding="utf-8"
        )
        for kind in MissionKind:
            self.assertNotIn(f"MissionKind.{kind.name}", controller_source)
        self.assertEqual(
            set(DEFAULT_EXECUTOR_FACTORIES), set(MissionKind), "every kind registered"
        )

    def test_the_controller_does_not_read_behavior_payloads(self):
        """It routes proposals; it does not interpret what they mean."""

        controller_source = (BOT / "engine" / "missions" / "controller.py").read_text(
            encoding="utf-8"
        )
        for behavior_word in ("banshee", "cloak", "harass", "rally", "anchor"):
            self.assertNotIn(behavior_word, controller_source.lower())


class UnitUtilityContractTests(unittest.TestCase):
    """§ preemption: priority alone must not decide who gets which unit."""

    def test_a_requirement_can_value_one_unit_type_above_another(self):
        requirement = UnitRequirement.combat(
            unit_types=frozenset({UnitTypeId.BANSHEE, UnitTypeId.SIEGETANK}),
            desired=2,
            minimum=1,
            type_desirability=(
                (UnitTypeId.SIEGETANK, 1.0),
                (UnitTypeId.BANSHEE, 0.9),
            ),
        )

        self.assertEqual(requirement.utility_for(tank(1)), 1.0)
        self.assertEqual(requirement.utility_for(banshee(2)), 0.9)

    def test_a_zero_utility_unit_is_never_requested(self):
        """Mutalisks overhead: a Banshee is worth nothing to that defense."""

        requirement = UnitRequirement.combat(
            unit_types=frozenset({UnitTypeId.BANSHEE, UnitTypeId.SIEGETANK}),
            desired=2,
            minimum=0,
            type_desirability=(
                (UnitTypeId.BANSHEE, 0.0),
                (UnitTypeId.SIEGETANK, 0.0),
            ),
        )

        self.assertEqual(requirement.utility_for(banshee(1)), 0.0)
        self.assertEqual(requirement.utility_for(tank(2)), 0.0)
        # Identity still matches -- utility, not eligibility, is what is zero.
        self.assertTrue(requirement.matches_identity(banshee(1)))

    def test_the_default_requirement_is_utility_neutral(self):
        requirement = UnitRequirement.combat(
            unit_types=frozenset({UnitTypeId.BANSHEE}), desired=1, minimum=1
        )
        self.assertEqual(requirement.utility_for(banshee(1)), 1.0)


if __name__ == "__main__":
    unittest.main()

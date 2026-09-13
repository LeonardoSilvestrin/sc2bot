"""Replay fixtures for the decision kernels a mathematical model may replace.

Each ``tests/replay/<kernel>.json`` holds cases: the exact inputs one kernel
reads and the exact output it produced when the fixture was recorded, at
machine precision, plus the fingerprint of every default configuration it
read. A replacement kernel reproduces every case, or the difference is
deliberate: regenerate with

    SC2BOT_REGENERATE_REPLAY=1 .venv/Scripts/python -m pytest tests/test_kernel_replay.py

and review the fixture diff in the same commit as the change.

- ``strategy_director``: ``StrategyInputs`` over time -> objective,
  confidence, every objective's contributions, intent.
- ``mission_policy``: ``StrategicContext`` + ``MissionSignals`` ->
  ``ControlNeed`` and the ``MissionEvaluation``.
- ``map_control_anchor``: spatial samples, held bases, army and context ->
  the selected anchor, its term breakdown, every ranked candidate, the
  signals and the plan. Sample order must not matter.
- ``unit_allocation``: unit snapshots + concrete requirements over time ->
  assignments, transfers, releases and owners. Unit order must not matter.
"""

from __future__ import annotations

import json
import os
import random
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app.run_identity import fingerprint
from bot.behavior.map_control import MapControlConfig, MapControlPlanner
from bot.engine.missions.allocator import UnitAllocator
from bot.engine.missions.models import UnitRequirement
from bot.strategy.config import StrategyConfig
from bot.strategy.context import StrategicContext
from bot.strategy.director import StrategicDirector
from bot.strategy.intent import (
    IntentConfig,
    StrategicActivity,
    StrategicIntent,
    derive_intent,
)
from bot.strategy.mission_policy import (
    ControlMatch,
    MissionPolicyConfig,
    MissionSignals,
    evaluate_mission,
)
from bot.strategy.model import StrategyInputs
from bot.strategy.spatial.model import (
    ControlObjective,
    ControlTargetKind,
    SpatialStrategySnapshot,
)
from bot.world.attention import AttentionSnapshot, MapFacts, UnitSnapshot, WorldFacts
from bot.world.awareness import (
    AwarenessSnapshot,
    RelativeStrength,
    SpatialField,
    SpatialFieldSample,
    ThreatAssessment,
)
from bot.world.awareness.bases import BaseAssessment, BaseAwareness, BaseSecurityLevel
from bot.world.awareness.enemy import EnemyAwareness

REPLAY_DIR = Path(__file__).with_name("replay")
REGENERATE = os.environ.get("SC2BOT_REGENERATE_REPLAY") == "1"
MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)


def plain(value: Any) -> Any:
    return json.loads(json.dumps(value, allow_nan=False))


def point(value: list[float]) -> Point2:
    return Point2((value[0], value[1]))


def xy(value: Point2) -> list[float]:
    return [float(value.x), float(value.y)]


def objective_from(data: dict[str, Any]) -> ControlObjective:
    return ControlObjective(
        objective_id=data["id"],
        kind=ControlTargetKind[data["kind"]],
        target_key=data["target"],
        position=point(data["position"]),
        activity=StrategicActivity[data["activity"]],
        desired_control=data["desired_control"],
        desired_visibility=data["desired_visibility"],
        importance=data["importance"],
        current_control=data["current_control"],
        current_visibility=data["current_visibility"],
        reason=data["reason"],
    )


def context_from(data: dict[str, Any]) -> StrategicContext:
    intent = data.get("intent")
    return StrategicContext(
        intent=derive_intent(None) if intent is None else StrategicIntent(**intent),
        spatial=SpatialStrategySnapshot(
            objectives=tuple(objective_from(item) for item in data["objectives"])
        ),
        revision=data["revision"],
    )


def signals_from(data: dict[str, Any]) -> MissionSignals:
    control = data.get("control")
    return MissionSignals(
        activity=None if data["activity"] is None else StrategicActivity[data["activity"]],
        opportunity=data.get("opportunity", 0.0),
        urgency=data.get("urgency", 0.0),
        risk=data.get("risk", 0.0),
        information_gain=data.get("information_gain", 0.0),
        control=(
            None
            if control is None
            else ControlMatch(control["objective_id"], control["alignment"])
        ),
        reason=data.get("reason", ""),
    )


def unit_from(data: dict[str, Any]) -> UnitSnapshot:
    return UnitSnapshot(
        tag=data["tag"],
        unit_type=UnitTypeId[data["type"]],
        position=point(data["position"]),
        health_percentage=data.get("health", 1.0),
        is_flying=data.get("flying", False),
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
        is_ready=data.get("ready", True),
        available_for_mission=data.get("available", True),
        supply_cost=data["supply"],
    )


def requirement_from(data: dict[str, Any]) -> UnitRequirement:
    return UnitRequirement.combat(
        unit_types=frozenset(UnitTypeId[name] for name in data["unit_types"]),
        desired=data["desired"],
        minimum=data["minimum"],
        minimum_health=data.get("minimum_health", 0.0),
        desirability=data.get("desirability", 1.0),
        type_desirability=tuple(
            (UnitTypeId[name], value) for name, value in data.get("type_desirability", ())
        ),
        supply_budget=data.get("supply_budget"),
    )


def sample_from(data: dict[str, Any]) -> SpatialFieldSample:
    return SpatialFieldSample(
        position=point(data["position"]),
        friendly_value=data.get("friendly_value", 0.0),
        friendly_control=data.get("friendly_control"),
        enemy_control=data.get("enemy_control", 0.0),
        enemy_threat=data.get("enemy_threat", 0.0),
        choke_value=data.get("choke_value", 0.0),
        route_value=data.get("route_value", 0.0),
        confidence=data.get("confidence", 0.0),
        knowledge_confidence=data.get("knowledge_confidence", 0.0),
    )


def strategy_director(case: dict[str, Any]) -> list[dict[str, Any]]:
    director = StrategicDirector(StrategyConfig())
    steps = []
    for step in case["steps"]:
        snapshot = director.update(StrategyInputs(**step["inputs"]), step["game_time"])
        previous = snapshot.previous_objective
        steps.append(
            {
                "objective": snapshot.objective.name,
                "leader": snapshot.leader.name,
                "previous_objective": None if previous is None else previous.name,
                "confidence": snapshot.confidence,
                "game_time": snapshot.game_time,
                "time_in_objective": snapshot.time_in_objective,
                "assessments": [
                    {
                        "objective": item.objective.name,
                        "score": item.score,
                        "raw_score": item.raw_score,
                        "contributions": [
                            [part.signal, part.contribution]
                            for part in item.contributions
                        ],
                    }
                    for item in snapshot.assessments
                ],
                "intent": derive_intent(snapshot, IntentConfig()).as_dict(),
            }
        )
    return steps


def mission_policy(case: dict[str, Any]) -> dict[str, Any]:
    # Exactly what MissionRanker.rank evaluates for one candidate.
    context = context_from(case["context"])
    signals = signals_from(case["signals"])
    need = context.need_for(
        None if signals.control is None else signals.control.objective_id
    )
    evaluation = evaluate_mission(
        signals, context.intent, need=need, config=MissionPolicyConfig()
    )
    return {
        "need": None if need is None else {"importance": need.importance, "gap": need.gap},
        "evaluation": evaluation.log_fields(),
    }


def map_control_anchor(
    case: dict[str, Any], order: Callable[[list[Any]], list[Any]] = list
) -> dict[str, Any]:
    now = case["time"]
    units = tuple(
        UnitSnapshot(
            tag=tag,
            unit_type=UnitTypeId.MARINE,
            position=MAP.own_start,
            health_percentage=1.0,
            is_flying=False,
            is_worker=False,
            can_attack_air=True,
            can_attack_ground=True,
            supply_cost=1.0,
        )
        for tag in range(1, case["marines"] + 1)
    )
    attention = AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=float(len(units)),
            supply_cap=200.0,
            own_units=units,
            enemy_units=(),
            map=MAP,
        )
    )
    awareness = AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=now,
        bases=BaseAwareness(
            tuple(
                BaseAssessment(
                    base["id"],
                    point(base["position"]),
                    base["is_main"],
                    0.0,
                    0.0,
                    BaseSecurityLevel.SAFE,
                )
                for base in order(case["bases"])
            )
        ),
        spatial=SpatialField(
            samples=tuple(sample_from(item) for item in order(case["samples"])),
            updated_at=now,
            sample_spacing=case["spacing"],
        ),
    )
    planner = MapControlPlanner(config=MapControlConfig())
    (candidate,) = planner.propose(attention, awareness, context_from(case["context"]))
    plan = planner.last_plan
    assert plan is not None
    return {
        "selected": next(
            item.log_fields() for item in planner.last_candidates if item.selected
        ),
        "signals": candidate.signals.log_fields(),
        "plan": {
            "anchor": xy(plan.anchor),
            "desired_units": plan.desired_units,
            "supply_budget": plan.supply_budget,
        },
        "ranked": [item.log_fields() for item in planner.last_candidates],
    }


def unit_allocation(
    case: dict[str, Any], order: Callable[[list[Any]], list[Any]] = list
) -> list[dict[str, Any]]:
    allocator = UnitAllocator(preemption_margin=case["preemption_margin"])
    tags: list[int] = []
    results = []
    for step in case["steps"]:
        if "sync" in step:
            units = tuple(unit_from(item) for item in order(step["sync"]))
            allocator.sync(units)
            tags = sorted(unit.tag for unit in units)
            continue
        call = step["allocate"]
        result = allocator.allocate(
            mission_id=call["mission_id"],
            priority=call["priority"],
            requirement=requirement_from(call["requirement"]),
            objective=None if call.get("objective") is None else point(call["objective"]),
            now=call["now"],
            can_preempt=call.get("can_preempt", False),
            commitment_seconds=call.get("commitment_seconds", 5.0),
            preferred_tags=frozenset(call.get("preferred_tags", ())),
            preemption_cost=call.get("preemption_cost", 0.0),
        )
        # As MissionController does: a released lease is dropped at once.
        allocator.release_units(call["mission_id"], result.released_tags)
        results.append(
            {
                "mission_id": call["mission_id"],
                "assigned": list(result.assigned_tags),
                "satisfied": result.requirements_satisfied,
                "transfers": [
                    [item.unit_tag, item.from_mission_id, item.to_mission_id]
                    for item in result.transfers
                ],
                "released": list(result.released_tags),
                "owners": {str(tag): allocator.owner_of(tag) for tag in tags},
            }
        )
    return results


def reversed_list(items: list[Any]) -> list[Any]:
    return list(reversed(items))


def shuffled_list(items: list[Any]) -> list[Any]:
    copy = list(items)
    random.Random(len(copy)).shuffle(copy)
    return copy


class KernelReplayTests(unittest.TestCase):
    def replay(
        self,
        kernel: str,
        compute: Callable[[dict[str, Any]], Any],
        configs: dict[str, Any],
    ) -> list[dict[str, Any]]:
        path = REPLAY_DIR / f"{kernel}.json"
        fixture = json.loads(path.read_text(encoding="utf-8"))
        fingerprints = {name: fingerprint(config) for name, config in configs.items()}
        outputs = [plain(compute(case["input"])) for case in fixture["cases"]]
        if REGENERATE:
            fixture["configs"] = fingerprints
            for case, output in zip(fixture["cases"], outputs, strict=True):
                case["expected"] = output
            path.write_bytes(
                (json.dumps(fixture, indent=2, allow_nan=False) + "\n").encode("utf-8")
            )
            return fixture["cases"]
        self.assertEqual(
            fixture["configs"],
            fingerprints,
            f"{kernel}: a default configuration changed; regenerate deliberately",
        )
        for case, output in zip(fixture["cases"], outputs, strict=True):
            with self.subTest(case=case["name"]):
                self.assertIsNotNone(case["expected"], "unrecorded case")
                self.assertEqual(output, case["expected"])
        return fixture["cases"]

    def test_strategy_director(self):
        self.replay(
            "strategy_director",
            strategy_director,
            {"strategy": StrategyConfig(), "intent": IntentConfig()},
        )

    def test_mission_policy(self):
        self.replay(
            "mission_policy",
            mission_policy,
            {"mission_policy": MissionPolicyConfig(), "intent": IntentConfig()},
        )

    def test_map_control_anchor(self):
        cases = self.replay(
            "map_control_anchor",
            map_control_anchor,
            {"map_control": MapControlConfig(), "intent": IntentConfig()},
        )
        for case in cases:
            for order in (reversed_list, shuffled_list):
                with self.subTest(case=case["name"], order=order.__name__):
                    self.assertEqual(
                        plain(map_control_anchor(case["input"], order)),
                        case["expected"],
                    )

    def test_unit_allocation(self):
        cases = self.replay("unit_allocation", unit_allocation, {})
        for case in cases:
            for order in (reversed_list, shuffled_list):
                with self.subTest(case=case["name"], order=order.__name__):
                    self.assertEqual(
                        plain(unit_allocation(case["input"], order)),
                        case["expected"],
                    )

    def test_every_fixture_file_is_replayed(self):
        replayed = {
            name.removeprefix("test_")
            for name in dir(self)
            if name.startswith("test_") and name != "test_every_fixture_file_is_replayed"
        }
        self.assertEqual({path.stem for path in REPLAY_DIR.glob("*.json")}, replayed)


# Keep the unused-import check honest: ``replace`` is used by callers that
# extend these builders; it is not needed here.
del replace


if __name__ == "__main__":
    unittest.main()

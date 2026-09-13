"""A decision is joinable through the log, from Strategy to the units.

Two causal chains read back from a real JSONL log:

    strategy.context -> mission.evaluated -> proposal_admitted
        -> units_assigned -> mission.progressed

    strategy.context -> mission.evaluated (rejected) -> nothing in the engine

Joins use only what the records carry: ``context_revision``,
``proposal_id``, ``mission_id``, and the envelope's ``seq`` for order.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.adapters.logging import JsonlBotLogger
from bot.app import BotRuntime
from bot.app.mission_ranking import MissionRanker
from bot.app.strategy_runtime import StrategyRuntime
from bot.behavior.contracts import UNRANKED_PRIORITY, MissionCandidate
from bot.engine.missions import (
    MissionController,
    MissionKind,
    MissionProposal,
    UnitRequirement,
)
from bot.engine.missions.execution import MissionOutcome, MissionResult
from bot.strategy import MissionSignals, StrategicActivity
from bot.world.attention import AttentionSnapshot, MapFacts, WorldFacts
from bot.world.awareness import AwarenessSnapshot, RelativeStrength, ThreatAssessment
from bot.world.awareness.enemy import EnemyAwareness
from tests.fakes import FakeCommands


def read_strict(path: Path) -> list[dict]:
    def refuse(constant: str) -> float:
        raise ValueError(f"non-strict JSON constant {constant}")

    return [
        json.loads(line, parse_constant=refuse)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def only(records, predicate) -> dict:
    matches = [record for record in records if predicate(record)]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one record, found {len(matches)}")
    return matches[0]


def first(records, predicate) -> dict:
    return next(record for record in records if predicate(record))


def unit(tag: int, unit_type: UnitTypeId) -> SimpleNamespace:
    return SimpleNamespace(
        tag=tag,
        type_id=unit_type,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        can_attack_air=False,
        can_attack_ground=True,
        is_ready=True,
        is_carrying_resource=False,
        is_constructing_scv=False,
        is_structure=False,
    )


class ViableDecisionChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_scout_is_joinable_from_its_context_to_its_progress(self):
        bot = SimpleNamespace(
            time=10.0,
            minerals=400,
            vespene=0,
            supply_used=16,
            supply_cap=23,
            units=(
                *(unit(tag, UnitTypeId.SCV) for tag in range(1, 17)),
                unit(17, UnitTypeId.REAPER),
            ),
            structures=(),
            enemy_units=(),
            enemy_structures=(),
            worker_type=UnitTypeId.SCV,
            start_location=Point2((10, 10)),
            enemy_start_locations=[Point2((90, 90))],
            game_info=SimpleNamespace(map_center=Point2((50, 50)), map_name="Trace"),
            mediator=SimpleNamespace(
                get_enemy_nat=Point2((80, 80)),
                get_unit_role_dict={"GATHERING": set(range(1, 17)), "IDLE": {17}},
            ),
        )
        bot.is_visible = lambda position: False

        with tempfile.TemporaryDirectory() as directory:
            logger = JsonlBotLogger(Path(directory), session_name="trace", run_id="t")
            runtime = BotRuntime(logger=logger, rng_seed=5)
            with (
                patch("bot.app.frame.AresMissionCommands", return_value=FakeCommands()),
                patch("bot.app.frame.register_baseline_behaviors"),
            ):
                await runtime.on_start(bot)
                await runtime.on_step(bot, iteration=1)
            logger.close()
            records = read_strict(logger.path)

        started = only(records, lambda r: r["event"] == "game.started")
        self.assertEqual(
            (started["data"]["rng_seed"], started["data"]["rng_seed_source"]),
            (5, "configured"),
        )
        self.assertTrue(started["data"]["config_fingerprint"])
        self.assertIsNone(started["iteration"])

        evaluation = first(
            records,
            lambda r: r["event"] == "mission.evaluated"
            and r["data"]["mission_kind"] == "SCOUT",
        )
        self.assertTrue(evaluation["data"]["viable"])
        proposal_id = evaluation["data"]["proposal_id"]
        context = only(
            records,
            lambda r: r["event"] == "strategy.context"
            and r["data"]["revision"] == evaluation["data"]["context_revision"],
        )
        admitted = only(
            records,
            lambda r: r["event"] == "proposal_admitted"
            and r["data"]["proposal_id"] == proposal_id,
        )
        mission_id = admitted["data"]["mission_id"]
        assigned = first(
            records,
            lambda r: r["event"] == "units_assigned"
            and r["data"]["mission_id"] == mission_id,
        )
        progressed = first(
            records,
            lambda r: r["event"] == "mission.progressed"
            and r["data"]["mission_id"] == mission_id,
        )

        chain = (context, evaluation, admitted, assigned, progressed)
        sequence = [record["seq"] for record in chain]
        self.assertEqual(sequence, sorted(sequence))
        self.assertEqual({record["iteration"] for record in chain}, {1})
        self.assertEqual({record["run"] for record in records}, {"t"})
        self.assertEqual(assigned["data"]["unit_tags"], [17])
        self.assertEqual(progressed["data"]["outcome"], "ACTIVE")
        # The context record is complete: intent and every control objective.
        self.assertIn("intent", context["data"])
        self.assertIn("control_objectives", context["data"])


class HoldsPosition:
    async def step(self, context) -> MissionResult:
        return MissionResult(MissionOutcome.ACTIVE, "holding")


class RejectedDecisionChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_rejected_raid_is_joinable_and_stops_at_the_policy(self):
        awareness = AwarenessSnapshot(
            enemy=EnemyAwareness(sightings=(), locations=()),
            relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
            threat=ThreatAssessment(0, 0, 0),
            updated_at=30.0,
        )
        attention = AttentionSnapshot(
            WorldFacts(
                iteration=3,
                time=30.0,
                minerals=0,
                vespene=0,
                supply_used=0.0,
                supply_cap=200.0,
                own_units=(),
                enemy_units=(),
                map=MapFacts(
                    center=Point2((50, 50)),
                    own_start=Point2((10, 10)),
                    enemy_starts=(Point2((90, 90)),),
                ),
            )
        )
        raid = MissionCandidate(
            draft=MissionProposal(
                proposal_id="raid:1",
                deduplication_key="harass:enemy_main",
                planner="raid_planner",
                kind=MissionKind.HARASS,
                priority=UNRANKED_PRIORITY,
                target_key="enemy_main",
                target=Point2((90, 90)),
                reason="test_raid",
                requirement=UnitRequirement.combat(
                    unit_types=frozenset({UnitTypeId.REAPER}), desired=1, minimum=1
                ),
                created_at=30.0,
                can_preempt=True,
            ),
            # All risk, nothing to gain: negative under any intent.
            signals=MissionSignals(activity=StrategicActivity.HARASS, risk=1.0),
        )

        with tempfile.TemporaryDirectory() as directory:
            logger = JsonlBotLogger(Path(directory), session_name="trace")
            strategy = StrategyRuntime(logger=logger)
            ranker = MissionRanker(logger=logger)
            controller = MissionController(
                logger=logger,
                executor_factories={
                    kind: (lambda mission, now: HoldsPosition()) for kind in MissionKind
                },
            )
            logger.begin_frame(3)
            strategy.update(awareness)
            strategy.record_context()
            proposals = ranker.rank((raid,), strategy.context)
            await controller.tick(
                attention=attention,
                awareness=awareness,
                proposals=proposals,
                commands=FakeCommands(),
                declared_planners=frozenset({"raid_planner"}),
            )
            logger.end_frame()
            logger.close()
            records = read_strict(logger.path)

        self.assertEqual(proposals, ())
        evaluation = only(records, lambda r: r["event"] == "mission.evaluated")
        self.assertFalse(evaluation["data"]["viable"])
        self.assertIsNone(evaluation["data"]["priority"])
        self.assertTrue(evaluation["data"]["reason"].startswith("rejected_"))
        context = only(
            records,
            lambda r: r["event"] == "strategy.context"
            and r["data"]["revision"] == evaluation["data"]["context_revision"],
        )
        self.assertLess(context["seq"], evaluation["seq"])
        self.assertEqual(
            [
                record
                for record in records
                if record["component"] == "engine.missions.controller"
                and record["data"].get("proposal_id") == "raid:1"
            ],
            [],
        )


if __name__ == "__main__":
    unittest.main()

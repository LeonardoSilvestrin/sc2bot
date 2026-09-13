"""Candidates become proposals only through the Mission Policy, and only when
they are worth executing."""

from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app.mission_ranking import MissionRanker, rank_candidates
from bot.app.run_identity import fingerprint
from bot.behavior.contracts import UNRANKED_PRIORITY, MissionCandidate
from bot.engine.missions import (
    MissionController,
    MissionKind,
    MissionMode,
    MissionProposal,
    MissionStatus,
    UnitRequirement,
)
from bot.engine.missions.allocator import UnitAllocator
from bot.engine.missions.execution import MissionOutcome, MissionResult
from bot.strategy import (
    FALLBACK_OWNER,
    MISSION_POLICY_MODEL,
    REJECTED_NEGATIVE_RAW_UTILITY,
    REJECTED_UTILITY_NOT_ABOVE_MINIMUM,
    VIABLE_BY_URGENCY_FLOOR,
    IntentConfig,
    MissionPolicyConfig,
    MissionSignals,
    StrategicActivity,
    StrategicContext,
    StrategicObjective,
)
from bot.world.attention import AttentionSnapshot, MapFacts, UnitSnapshot, WorldFacts
from bot.world.awareness import AwarenessSnapshot, RelativeStrength, ThreatAssessment
from bot.world.awareness.enemy import EnemyAwareness
from tests.fakes import FakeCommands, FakeLogger

PROFILES = IntentConfig()
MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)


def context(objective: StrategicObjective, **intent: float) -> StrategicContext:
    return StrategicContext(intent=replace(PROFILES.profile(objective), **intent))


def draft(
    key: str = "map_control:patrol",
    *,
    now: float = 10.0,
    planner: str = "test_planner",
    kind: MissionKind = MissionKind.MAP_CONTROL,
    mode: MissionMode = MissionMode.FINITE,
    sequence: int = 1,
    desired: int = 1,
    minimum: int = 1,
) -> MissionProposal:
    return MissionProposal(
        proposal_id=f"{key}:{sequence}",
        deduplication_key=key,
        planner=planner,
        kind=kind,
        priority=UNRANKED_PRIORITY,
        target_key=key,
        target=Point2((40, 40)),
        reason="test_opportunity",
        requirement=UnitRequirement.combat(
            unit_types=frozenset({UnitTypeId.MARINE}),
            desired=desired,
            minimum=minimum,
        ),
        created_at=now,
        can_preempt=True,
        commitment_seconds=1.0,
        mode=mode,
    )


def patrol(*, now: float = 10.0, opportunity: float = 0.6) -> MissionCandidate:
    return MissionCandidate(
        draft=draft(now=now),
        signals=MissionSignals(
            activity=StrategicActivity.MAP_CONTROL,
            opportunity=opportunity,
            information_gain=0.4,
            risk=0.1,
            reason="frontier_candidate",
        ),
    )


def worthless(*, now: float = 10.0, sequence: int = 1) -> MissionCandidate:
    """A raid whose risk outweighs everything it offers: raw utility < 0."""

    return MissionCandidate(
        draft=draft(
            "harass:enemy_main", now=now, kind=MissionKind.HARASS, sequence=sequence
        ),
        signals=MissionSignals(
            activity=StrategicActivity.HARASS, risk=1.0, reason="suicide_raid"
        ),
    )


def empty(*, now: float = 10.0) -> MissionCandidate:
    """A candidate offering nothing at all: utility exactly 0."""

    return MissionCandidate(
        draft=draft("map_control:nowhere", now=now),
        signals=MissionSignals(activity=StrategicActivity.MAP_CONTROL),
    )


def standing(*, now: float, sequence: int, desired: int) -> MissionCandidate:
    return MissionCandidate(
        draft=draft(
            "hold_rally:main_army",
            now=now,
            planner="standing_planner",
            kind=MissionKind.HOLD_RALLY,
            mode=MissionMode.STANDING,
            sequence=sequence,
            desired=desired,
            minimum=0,
        ),
        signals=MissionSignals.fallback("idle_army"),
    )


def marine(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
    )


class HoldsPosition:
    async def step(self, context) -> MissionResult:
        return MissionResult(MissionOutcome.ACTIVE, "holding")


FACTORIES = {kind: (lambda mission, now: HoldsPosition()) for kind in MissionKind}


class CandidateContractTests(unittest.TestCase):
    def test_a_planner_cannot_hand_in_a_ranked_draft(self):
        with self.assertRaises(ValueError):
            MissionCandidate(
                draft=replace(draft(), priority=95),
                signals=MissionSignals(activity=StrategicActivity.DEFENSE),
            )

    def test_ranking_changes_only_the_priority(self):
        candidate = patrol()

        (proposal,) = rank_candidates((candidate,))

        self.assertNotEqual(proposal.priority, UNRANKED_PRIORITY)
        self.assertEqual(replace(proposal, priority=UNRANKED_PRIORITY), candidate.draft)


class StrategyShapesRankingTests(unittest.TestCase):
    def test_the_same_opportunity_ranks_higher_when_strategy_wants_it(self):
        candidate = patrol()

        (building,) = rank_candidates(
            (candidate,), context(StrategicObjective.BUILD_ADVANTAGE)
        )
        (controlling,) = rank_candidates(
            (candidate,), context(StrategicObjective.TAKE_MAP_CONTROL)
        )

        self.assertGreater(controlling.priority, building.priority)

    def test_without_a_context_the_neutral_intent_ranks(self):
        candidate = patrol()

        self.assertEqual(
            rank_candidates((candidate,)),
            rank_candidates((candidate,), StrategicContext.neutral()),
        )


class ViabilityGateTests(unittest.TestCase):
    def test_rejected_candidates_never_become_proposals(self):
        ranker = MissionRanker()

        proposals = ranker.rank((worthless(), empty(), patrol()))

        self.assertEqual(
            [proposal.deduplication_key for proposal in proposals],
            ["map_control:patrol"],
        )
        self.assertEqual(
            ranker.last_evaluations["harass:enemy_main"].reason,
            REJECTED_NEGATIVE_RAW_UTILITY,
        )
        self.assertEqual(
            ranker.last_evaluations["map_control:nowhere"].reason,
            REJECTED_UTILITY_NOT_ABOVE_MINIMUM,
        )

    def test_standing_is_accepted_at_its_fixed_fallback_priority(self):
        ranker = MissionRanker()

        (proposal,) = ranker.rank((standing(now=10.0, sequence=1, desired=3),))

        self.assertEqual(proposal.priority, MissionPolicyConfig().fallback_priority)
        self.assertEqual(
            ranker.last_evaluations["hold_rally:main_army"].reason, FALLBACK_OWNER
        )


class EvaluationLogTests(unittest.TestCase):
    def test_every_outcome_is_logged_including_rejections(self):
        logger = FakeLogger()
        ranker = MissionRanker(logger=logger)
        candidates = (worthless(), empty(), patrol())

        ranker.rank(candidates)
        # A repeated identical decision is still a decision: it is logged too.
        ranker.rank((patrol(now=12.0),))

        self.assertEqual(
            [event["name"] for event in logger.events], ["mission.evaluated"] * 4
        )
        by_id = {event["data"]["proposal_id"]: event["data"] for event in logger.events}
        for candidate in candidates:
            self.assertIn(candidate.draft.proposal_id, by_id)
        rejected = by_id["harass:enemy_main:1"]
        self.assertFalse(rejected["viable"])
        self.assertIsNone(rejected["priority"])
        self.assertEqual(rejected["reason"], REJECTED_NEGATIVE_RAW_UTILITY)
        self.assertLess(rejected["evaluation"]["raw_utility"], 0.0)
        self.assertEqual(rejected["evaluation"]["utility"], 0.0)
        accepted = by_id["map_control:patrol:1"]
        self.assertTrue(accepted["viable"])
        self.assertEqual(accepted["planner"], "test_planner")
        self.assertEqual(accepted["signals"]["activity"], "MAP_CONTROL")
        for name in (
            "utility",
            "raw_utility",
            "urgency_floor",
            "priority",
            "strategic_desirability",
            "risk_penalty",
            "urgency_contribution",
            "control_contribution",
        ):
            self.assertIn(name, accepted["evaluation"])
        self.assertEqual(accepted["priority"], accepted["evaluation"]["priority"])


class EvaluationProvenanceTests(unittest.TestCase):
    def test_an_evaluation_cites_its_context_model_and_configuration(self):
        logger = FakeLogger()
        ranker = MissionRanker(logger=logger)
        strategy = replace(context(StrategicObjective.PRESSURE), revision=4)

        ranker.rank((patrol(),), strategy)

        (event,) = logger.events
        self.assertEqual(event["data"]["context_revision"], 4)
        self.assertEqual(event["data"]["policy_model"], MISSION_POLICY_MODEL)
        self.assertEqual(
            event["data"]["policy_config"], fingerprint(MissionPolicyConfig())
        )
        stricter = MissionRanker(config=MissionPolicyConfig(minimum_viable_utility=0.2))
        self.assertNotEqual(stricter.config_fingerprint, ranker.config_fingerprint)

    def test_evaluations_are_logged_at_machine_precision(self):
        logger = FakeLogger()
        ranker = MissionRanker(logger=logger)

        ranker.rank((patrol(opportunity=0.123456789),))

        data = logger.events[0]["data"]
        evaluation = ranker.last_evaluations["map_control:patrol"]
        self.assertEqual(data["signals"]["opportunity"], 0.123456789)
        self.assertEqual(data["evaluation"]["utility"], evaluation.utility)
        self.assertEqual(data["evaluation"]["raw_utility"], evaluation.raw_utility)


class RejectedWorkInTheEngineTests(unittest.IsolatedAsyncioTestCase):
    """Rejection happens before the engine: nothing rejected is admitted,
    leased, or allowed to preempt."""

    async def tick(self, controller, ranker, now, units, candidates, strategy=None):
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
        )
        await controller.tick(
            attention=attention,
            awareness=awareness,
            proposals=ranker.rank(candidates, strategy),
            commands=FakeCommands(),
            declared_planners=frozenset(
                candidate.draft.planner for candidate in candidates
            ),
        )

    def setUp(self):
        self.logger = FakeLogger()
        self.controller = MissionController(
            logger=self.logger, executor_factories=FACTORIES
        )
        self.ranker = MissionRanker(logger=self.logger)
        self.units = (marine(1), marine(2))

    def owners(self):
        return {self.controller.allocator.owner_of(unit.tag) for unit in self.units}

    async def test_a_rejected_candidate_never_reaches_the_controller_or_a_unit(self):
        await self.tick(
            self.controller,
            self.ranker,
            10.0,
            self.units,
            (standing(now=10.0, sequence=1, desired=2),),
        )
        main = self.controller.board.live_for_key("hold_rally:main_army")

        # Past standing's commitment window, a preempting raid is rejected.
        await self.tick(
            self.controller,
            self.ranker,
            12.0,
            self.units,
            (worthless(now=12.0),),
            context(StrategicObjective.BUILD_ADVANTAGE, harass=0.0, risk_tolerance=0.0),
        )

        self.assertIsNone(self.controller.board.live_for_key("harass:enemy_main"))
        controller_ids = {
            event["data"].get("proposal_id")
            for event in self.logger.events
            if event["component"] == "engine.missions.controller"
        }
        self.assertNotIn("harass:enemy_main:1", controller_ids)
        self.assertEqual(self.owners(), {main.mission_id})
        self.assertFalse(
            [e for e in self.logger.events if e["name"] == "units_reassigned"]
        )

    async def test_a_withdrawn_standing_responsibility_returns_its_units(self):
        live_patrol = MissionCandidate(
            draft=draft(
                "map_control:patrol",
                now=10.0,
                planner="patrol_planner",
                mode=MissionMode.STANDING,
                desired=1,
                minimum=0,
            ),
            signals=patrol().signals,
        )
        await self.tick(
            self.controller,
            self.ranker,
            10.0,
            self.units,
            (live_patrol, standing(now=10.0, sequence=1, desired=2)),
        )
        mission = self.controller.board.live_for_key("map_control:patrol")
        self.assertEqual(len(mission.assigned_unit_tags), 1)

        # The patrol planner declares its slot again, but it is now worthless.
        withdrawn = replace(
            live_patrol,
            draft=replace(live_patrol.draft, proposal_id="map_control:patrol:2"),
            signals=MissionSignals(activity=StrategicActivity.MAP_CONTROL),
        )
        await self.tick(
            self.controller,
            self.ranker,
            15.0,
            self.units,
            (withdrawn, standing(now=15.0, sequence=2, desired=2)),
        )

        main = self.controller.board.live_for_key("hold_rally:main_army")
        self.assertEqual(mission.status, MissionStatus.CANCELLED)
        self.assertEqual(mission.last_reason, "standing_proposal_omitted")
        self.assertEqual(self.owners(), {main.mission_id})

    async def test_urgent_defense_stays_viable_and_preempts_the_fallback_owner(self):
        await self.tick(
            self.controller,
            self.ranker,
            10.0,
            self.units,
            (standing(now=10.0, sequence=1, desired=2),),
        )
        # Moderately urgent, very risky, and Strategy wants no defense at all:
        # the ordinary terms net negative, the emergency floor does not.
        defense = MissionCandidate(
            draft=draft(
                "defense:natural",
                now=12.0,
                planner="defense_planner",
                kind=MissionKind.DEFENSE,
            ),
            signals=MissionSignals(
                activity=StrategicActivity.DEFENSE, urgency=0.6, risk=1.0
            ),
        )

        await self.tick(
            self.controller,
            self.ranker,
            12.0,
            self.units,
            (defense,),
            context(StrategicObjective.PRESSURE, defense=0.0, risk_tolerance=0.0),
        )

        evaluation = self.ranker.last_evaluations["defense:natural"]
        self.assertLess(evaluation.raw_utility, 0.0)
        self.assertEqual(evaluation.reason, VIABLE_BY_URGENCY_FLOOR)
        live = self.controller.board.live_for_key("defense:natural")
        self.assertEqual(len(live.assigned_unit_tags), 1)
        self.assertIn(live.mission_id, self.owners())

    async def test_standing_receives_every_unit_no_viable_mission_wants(self):
        await self.tick(
            self.controller,
            self.ranker,
            10.0,
            self.units,
            (empty(), worthless(), standing(now=10.0, sequence=1, desired=2)),
        )

        main = self.controller.board.live_for_key("hold_rally:main_army")
        self.assertEqual(self.owners(), {main.mission_id})
        live = self.controller.board.live()
        self.assertEqual(
            [mission.proposal.deduplication_key for mission in live],
            ["hold_rally:main_army"],
        )


class CentralPriorityPreemptionTests(unittest.TestCase):
    """The allocator arbitrates the final, centrally ranked number."""

    def allocate(self, allocator, mission_id, priority, *, now):
        return allocator.allocate(
            mission_id=mission_id,
            priority=priority,
            requirement=UnitRequirement.combat(
                unit_types=frozenset({UnitTypeId.MARINE}), desired=1, minimum=1
            ),
            objective=None,
            now=now,
            can_preempt=True,
            commitment_seconds=1.0,
        )

    def test_a_re_ranked_mission_defends_its_units_at_its_current_priority(self):
        allocator = UnitAllocator()
        allocator.sync((marine(1),))
        self.allocate(allocator, "patrol", 30, now=0.0)
        # Strategy now wants map control: the same mission ranks higher.
        self.allocate(allocator, "patrol", 60, now=5.0)

        raid = self.allocate(allocator, "raid", 65, now=10.0)

        self.assertEqual(raid.assigned_tags, ())
        self.assertEqual(allocator.owner_of(1), "patrol")

    def test_a_clearly_higher_ranked_mission_still_preempts(self):
        allocator = UnitAllocator()
        allocator.sync((marine(1),))
        self.allocate(allocator, "patrol", 60, now=0.0)

        defense = self.allocate(allocator, "defense", 96, now=10.0)

        self.assertEqual(defense.assigned_tags, (1,))
        self.assertEqual(allocator.owner_of(1), "defense")


if __name__ == "__main__":
    unittest.main()

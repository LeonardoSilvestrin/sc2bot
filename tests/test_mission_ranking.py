"""Candidates become proposals only through the Mission Policy."""

from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app.mission_ranking import MissionRanker, rank_candidates
from bot.behavior.contracts import UNRANKED_PRIORITY, MissionCandidate
from bot.engine.missions import MissionKind, MissionProposal, UnitRequirement
from bot.engine.missions.allocator import UnitAllocator
from bot.strategy import (
    IntentConfig,
    MissionSignals,
    StrategicActivity,
    StrategicContext,
    StrategicObjective,
)
from bot.world.attention import UnitSnapshot
from tests.fakes import FakeLogger

PROFILES = IntentConfig()


def context(objective: StrategicObjective) -> StrategicContext:
    return StrategicContext(intent=PROFILES.profile(objective))


def draft(key: str = "map_control:patrol", *, now: float = 10.0) -> MissionProposal:
    return MissionProposal(
        proposal_id=f"{key}:1",
        deduplication_key=key,
        planner="test_planner",
        kind=MissionKind.MAP_CONTROL,
        priority=UNRANKED_PRIORITY,
        target_key=key,
        target=Point2((40, 40)),
        reason="test_opportunity",
        requirement=UnitRequirement.combat(
            unit_types=frozenset({UnitTypeId.MARINE}), desired=1, minimum=1
        ),
        created_at=now,
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


class RankingLogTests(unittest.TestCase):
    def test_candidate_and_ranking_are_logged_together_once_per_change(self):
        logger = FakeLogger()
        ranker = MissionRanker(logger=logger)

        ranker.rank((patrol(now=10.0),))
        ranker.rank((patrol(now=12.0),))
        ranker.rank((patrol(now=14.0, opportunity=0.9),))

        names = [event["name"] for event in logger.events]
        self.assertEqual(
            names,
            ["mission.candidate", "mission.ranked"] * 2,
        )
        candidate, ranked = logger.events[:2]
        self.assertEqual(candidate["data"]["planner"], "test_planner")
        self.assertEqual(candidate["data"]["activity"], "MAP_CONTROL")
        for field in ("opportunity", "urgency", "risk", "information_gain"):
            self.assertIn(field, candidate["data"])
        for field in (
            "utility",
            "priority",
            "strategic_desirability",
            "risk_penalty",
            "urgency_contribution",
            "control_contribution",
        ):
            self.assertIn(field, ranked["data"])


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

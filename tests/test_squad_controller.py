from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app.mission_registry import DEFAULT_EXECUTOR_FACTORIES
from bot.behavior.standing import StandingPlanner
from bot.engine.missions import (
    MissionController,
    MissionKind,
    MissionProposal,
    MissionStatus,
    UnitRequirement,
)
from bot.world.attention import AttentionSnapshot, MapFacts, UnitSnapshot, WorldFacts
from bot.world.awareness import AwarenessService
from tests.fakes import FakeCommands, FakeLogger

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)


def marine(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=MAP.own_start,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
    )


def enemy(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.ZERGLING,
        position=Point2((12, 12)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
    )


def attention(now: float, *, threatened: bool) -> AttentionSnapshot:
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=5,
            supply_cap=20,
            own_units=tuple(marine(tag) for tag in range(1, 6)),
            enemy_units=(enemy(100),) if threatened else (),
            map=MAP,
        )
    )


def defense(now: float) -> MissionProposal:
    return MissionProposal(
        proposal_id=f"defense:{now}",
        deduplication_key="defense:own_base",
        planner="test_defense",
        kind=MissionKind.DEFENSE,
        priority=95,
        target_key="own_base",
        target=Point2((12, 12)),
        reason="test_base_threat",
        requirement=UnitRequirement.combat(
            unit_types=frozenset({UnitTypeId.MARINE}), desired=2, minimum=2
        ),
        created_at=now,
        can_preempt=True,
        commitment_seconds=0.0,
    )


class SquadLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_defense_preempts_members_then_same_squad_returns_home(self):
        logger = FakeLogger()
        controller = MissionController(
            logger=logger, executor_factories=DEFAULT_EXECUTOR_FACTORIES
        )
        planner = StandingPlanner()
        service = AwarenessService()
        commands = FakeCommands()

        current = attention(10.0, threatened=False)
        aware = service.update(current)
        await controller.tick(
            attention=current,
            awareness=aware,
            proposals=planner.propose(current, aware),
            commands=commands,
        )
        home = controller.board.live_for_key("hold_rally:main_army")
        self.assertIsNotNone(home)
        original_members = controller.squads.get("main_army").member_tags.copy()
        self.assertEqual(len(original_members), 5)

        current = attention(12.0, threatened=True)
        aware = service.update(current)
        await controller.tick(
            attention=current,
            awareness=aware,
            proposals=(defense(12.0),),
            commands=commands,
        )
        squad = controller.squads.get("main_army")
        defense_mission = controller.board.live_for_key("defense:own_base")
        self.assertEqual(squad.current_mission_id, defense_mission.mission_id)
        self.assertEqual(squad.member_tags, original_members)

        current = attention(13.0, threatened=False)
        aware = service.update(current)
        await controller.tick(
            attention=current, awareness=aware, proposals=(), commands=commands
        )
        squad = controller.squads.get("main_army")
        self.assertEqual(squad.current_mission_id, home.mission_id)
        self.assertEqual(squad.member_tags, original_members)
        self.assertEqual(
            controller.board.get(defense_mission.mission_id).status,
            MissionStatus.COMPLETED,
        )
        names = [event["name"] for event in logger.events]
        self.assertIn("squad_created", names)
        self.assertIn("squad_preempted", names)
        self.assertIn("squad_returned_home", names)


if __name__ == "__main__":
    unittest.main()

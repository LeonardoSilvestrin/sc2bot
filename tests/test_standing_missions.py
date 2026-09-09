from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app.mission_registry import DEFAULT_EXECUTOR_FACTORIES
from bot.behavior.army import DispositionPlanner
from bot.engine.missions import (
    MissionController,
    MissionKind,
    MissionMode,
    MissionOutcome,
    MissionProposal,
    MissionResult,
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


def marine(tag: int, position: Point2 = MAP.own_start) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
    )


def attention(
    now: float,
    units: tuple[UnitSnapshot, ...],
    *,
    enemy_units: tuple[UnitSnapshot, ...] = (),
) -> AttentionSnapshot:
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=0.0,
            supply_cap=0.0,
            own_units=units,
            enemy_units=enemy_units,
            map=MAP,
        )
    )


def enemy_marine(tag: int, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
        visible_now=True,
    )


def harass_proposal(now: float, *, priority: int = 60) -> MissionProposal:
    return MissionProposal(
        proposal_id=f"test_harass:{now}",
        deduplication_key="harass:test",
        planner="test_harass",
        kind=MissionKind.HARASS,
        priority=priority,
        target_key="enemy_natural",
        target=Point2((80, 80)),
        reason="test_harass_opportunity",
        requirement=UnitRequirement.combat(
            unit_types=frozenset({UnitTypeId.MARINE}), desired=1, minimum=1
        ),
        created_at=now,
        timeout_seconds=60.0,
        cooldown_seconds=5.0,
        can_preempt=True,
        commitment_seconds=1.0,
        mode=MissionMode.FINITE,
    )


def defense_proposal(
    now: float, *, priority: int = 90, desired: int = 3
) -> MissionProposal:
    return MissionProposal(
        proposal_id=f"test_defense:{now}",
        deduplication_key="defense:own_base",
        planner="test_defense",
        kind=MissionKind.DEFENSE,
        priority=priority,
        target_key="own_base",
        target=MAP.own_start,
        reason="test_defense_threat",
        requirement=UnitRequirement.combat(
            unit_types=frozenset({UnitTypeId.MARINE}), desired=desired, minimum=1
        ),
        created_at=now,
        timeout_seconds=60.0,
        cooldown_seconds=5.0,
        can_preempt=True,
        commitment_seconds=1.0,
        mode=MissionMode.FINITE,
    )


class ImmediateCompletionExecutor:
    """Finishes on its very first step, regardless of context.

    Standing-in for the real ``WorkerLineHarassExecutor``/``DefendBaseExecutor``
    (which need actual enemy visibility/threats to complete), so Test D can
    deterministically drive a FINITE mission to completion and observe what
    happens next, without coupling this test to unrelated executor logic.
    """

    async def step(self, context) -> MissionResult:
        return MissionResult(MissionOutcome.COMPLETED, "test_mission_done")


class StandingOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_free_combat_unit_ends_up_leased_to_a_position_mission(self):
        """Test A: idle combat units, no other demand -> all end up in POSITION."""

        units = tuple(marine(tag) for tag in range(1, 6))
        current = attention(10.0, units)
        awareness = AwarenessService().update(current)
        disposition = DispositionPlanner()
        controller = MissionController(
            logger=FakeLogger(), executor_factories=DEFAULT_EXECUTOR_FACTORIES
        )
        commands = FakeCommands()

        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=disposition.propose(current, awareness),
            commands=commands,
        )

        for unit in units:
            owner_id = controller.allocator.owner_of(unit.tag)
            self.assertIsNotNone(owner_id)
            owner = controller.board.get(owner_id)
            self.assertEqual(owner.proposal.kind, MissionKind.POSITION)


class HarassPreemptsPositioningTests(unittest.IsolatedAsyncioTestCase):
    async def test_harass_acquires_a_unit_previously_holding_position(self):
        """Test B: a higher-priority HARASS proposal preempts a standing unit."""

        units = tuple(marine(tag) for tag in range(1, 4))
        service = AwarenessService()
        controller = MissionController(
            logger=FakeLogger(), executor_factories=DEFAULT_EXECUTOR_FACTORIES
        )
        commands = FakeCommands()
        disposition = DispositionPlanner()

        current = attention(10.0, units)
        awareness = service.update(current)
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=disposition.propose(current, awareness),
            commands=commands,
        )
        self.assertTrue(
            all(controller.allocator.owner_of(u.tag) is not None for u in units)
        )

        # Past the standing missions' commitment window (2.0s).
        current = attention(12.0, units)
        awareness = service.update(current)
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=(harass_proposal(12.0),),
            commands=commands,
        )

        harass = next(
            m for m in controller.board.live() if m.proposal.kind is MissionKind.HARASS
        )
        self.assertEqual(harass.status, MissionStatus.ACTIVE)
        self.assertEqual(len(harass.assigned_unit_tags), 1)
        self.assertEqual(
            controller.allocator.owner_of(harass.assigned_unit_tags[0]),
            harass.mission_id,
        )


class DefensePreemptsStandingAndHarassTests(unittest.IsolatedAsyncioTestCase):
    async def test_defense_acquires_force_from_position_and_harass(self):
        """Test C: DEFENSE outranks both standing POSITION and live HARASS."""

        units = tuple(marine(tag) for tag in range(1, 4))
        service = AwarenessService()
        controller = MissionController(
            logger=FakeLogger(), executor_factories=DEFAULT_EXECUTOR_FACTORIES
        )
        commands = FakeCommands()
        disposition = DispositionPlanner()

        current = attention(10.0, units)
        awareness = service.update(current)
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=disposition.propose(current, awareness),
            commands=commands,
        )

        # Past the standing missions' commitment window (2.0s).
        current = attention(12.0, units)
        awareness = service.update(current)
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=(harass_proposal(12.0),),
            commands=commands,
        )

        # Past harass's own commitment window (1.0s) too. A real threat is
        # present so DefendBaseExecutor has something to engage instead of
        # completing immediately on its first (same-tick) step.
        current = attention(
            14.0, units, enemy_units=(enemy_marine(999, Point2((12, 10))),)
        )
        awareness = service.update(current)
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=(defense_proposal(14.0, desired=3),),
            commands=commands,
        )

        defense = next(
            m for m in controller.board.live() if m.proposal.kind is MissionKind.DEFENSE
        )
        self.assertEqual(defense.status, MissionStatus.ACTIVE)
        self.assertEqual(len(defense.assigned_unit_tags), 3)
        for unit in units:
            self.assertEqual(
                controller.allocator.owner_of(unit.tag), defense.mission_id
            )

        # The standing missions were drained, not failed -- minimum=0.
        for mission in controller.board.live():
            if mission.proposal.kind is MissionKind.POSITION:
                self.assertFalse(mission.status.terminal)


class ReturnToStandingAfterFiniteMissionEndsTests(unittest.IsolatedAsyncioTestCase):
    async def test_units_return_to_position_once_a_finite_mission_completes(self):
        """Test D: no procedural "send back to reserve" -- it emerges from the
        next tick of proposals + allocation once HARASS finishes."""

        units = tuple(marine(tag) for tag in range(1, 4))
        service = AwarenessService()
        executor_factories = dict(DEFAULT_EXECUTOR_FACTORIES)
        executor_factories[MissionKind.HARASS] = (
            lambda mission, now: ImmediateCompletionExecutor()
        )
        controller = MissionController(
            logger=FakeLogger(), executor_factories=executor_factories
        )
        commands = FakeCommands()
        disposition = DispositionPlanner()

        current = attention(10.0, units)
        awareness = service.update(current)
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=disposition.propose(current, awareness),
            commands=commands,
        )

        # Past the standing missions' commitment window (2.0s).
        current = attention(12.0, units)
        awareness = service.update(current)
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=(harass_proposal(12.0),),
            commands=commands,
        )
        # The mission already completed within this same tick (allocation
        # and executor advancement happen in one pass), so it is no longer
        # "live" -- look it up via the full snapshot history instead.
        harass = next(
            m for m in controller.snapshots() if m.kind is MissionKind.HARASS
        )
        self.assertEqual(harass.status, MissionStatus.COMPLETED)

        # Check every unit is owned by a POSITION mission again after one
        # more tick with no new proposals at all -- nothing procedurally
        # reassigns the freed unit; it is simply "free" again for the
        # already-live standing missions to reclaim on their normal
        # allocate() pass.
        current = attention(13.0, units)
        awareness = service.update(current)
        await controller.tick(
            attention=current, awareness=awareness, proposals=(), commands=commands
        )

        for unit in units:
            owner_id = controller.allocator.owner_of(unit.tag)
            self.assertIsNotNone(owner_id)
            owner = controller.board.get(owner_id)
            self.assertEqual(owner.proposal.kind, MissionKind.POSITION)


class StandingMissionUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_updating_a_standing_proposal_refreshes_the_live_mission_in_place(
        self,
    ):
        """Test E: a new STANDING proposal for a live key updates, not rejects."""

        units = tuple(marine(tag) for tag in range(1, 8))
        service = AwarenessService()
        logger = FakeLogger()
        controller = MissionController(
            logger=logger, executor_factories=DEFAULT_EXECUTOR_FACTORIES
        )
        commands = FakeCommands()

        def third_proposal(
            now: float, *, desired: int, priority: int
        ) -> MissionProposal:
            return MissionProposal(
                proposal_id=f"disposition_planner:third:{now}",
                deduplication_key="position:third",
                planner="disposition_planner",
                kind=MissionKind.POSITION,
                priority=priority,
                target_key="position:third",
                target=Point2((70, 70)),
                reason="standing_disposition_third",
                requirement=UnitRequirement.combat(
                    unit_types=frozenset({UnitTypeId.MARINE}),
                    desired=desired,
                    minimum=0,
                ),
                created_at=now,
                timeout_seconds=3600.0,
                cooldown_seconds=5.0,
                can_preempt=True,
                commitment_seconds=2.0,
                mode=MissionMode.STANDING,
            )

        current = attention(10.0, units)
        awareness = service.update(current)
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=(third_proposal(10.0, desired=3, priority=30),),
            commands=commands,
        )
        first_mission = controller.board.live_for_key("position:third")
        self.assertEqual(len(first_mission.assigned_unit_tags), 3)
        mission_id = first_mission.mission_id

        current = attention(13.0, units)
        awareness = service.update(current)
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=(third_proposal(13.0, desired=6, priority=45),),
            commands=commands,
        )

        updated = controller.board.live_for_key("position:third")
        self.assertEqual(updated.mission_id, mission_id)
        self.assertEqual(updated.proposal.requirement.desired, 6)
        self.assertEqual(updated.proposal.priority, 45)
        self.assertEqual(len(updated.assigned_unit_tags), 6)
        self.assertEqual(len(controller.board.live()), 1)

        event_names = [event["name"] for event in logger.events]
        self.assertIn("standing_mission_updated", event_names)
        self.assertNotIn("proposal_rejected", event_names)


if __name__ == "__main__":
    unittest.main()

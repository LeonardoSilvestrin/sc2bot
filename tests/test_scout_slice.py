from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.adapters.ares.mission_commands import AresMissionCommands
from bot.app.mission_registry import DEFAULT_EXECUTOR_FACTORIES
from bot.behavior.scouting import IntelPlanner
from bot.engine.missions import (
    MissionController,
    MissionOutcome,
    MissionResult,
    MissionStatus,
    UnitRequirement,
)
from bot.world.attention import (
    AttentionSnapshot,
    MapFacts,
    MapObservation,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness import AwarenessService
from tests.fakes import FakeCommands, FakeLogger

TARGET = Point2((80, 80))


def worker(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.SCV,
        position=Point2((10 + tag, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=True,
        can_attack_air=False,
        can_attack_ground=True,
    )


def reaper(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.REAPER,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
    )


def attention(
    time: float, *, visible: bool, workers: int = 16, reapers: int = 1
) -> AttentionSnapshot:
    world = WorldFacts(
        iteration=int(time),
        time=time,
        minerals=500,
        vespene=0,
        supply_used=float(workers),
        supply_cap=30,
        own_units=(
            *(worker(tag) for tag in range(1, workers + 1)),
            *(reaper(9000 + tag) for tag in range(reapers)),
        ),
        enemy_units=(),
        map=MapFacts(
            center=Point2((50, 50)),
            own_start=Point2((10, 10)),
            enemy_starts=(Point2((90, 90)),),
            observations=(MapObservation("enemy_natural", TARGET, visible),),
        ),
    )
    return AttentionSnapshot(world)


class ScoutVerticalSliceTests(unittest.IsolatedAsyncioTestCase):
    async def test_preemption_recipient_completion_does_not_restart_donor(self):
        class CompleteUrgentExecutor:
            async def step(self, context):
                return MissionResult(MissionOutcome.COMPLETED, "urgent_done")

        service = AwarenessService()
        current = attention(10, visible=False)
        awareness = service.update(current)
        proposal = IntelPlanner().propose(current, awareness)[0]
        default_factory = DEFAULT_EXECUTOR_FACTORIES[proposal.kind]
        controller = MissionController(
            logger=FakeLogger(),
            executor_factories={
                proposal.kind: lambda mission, now: (
                    CompleteUrgentExecutor()
                    if mission.proposal.priority == 100
                    else default_factory(mission, now)
                )
            },
        )
        commands = FakeCommands()
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=(proposal,),
            commands=commands,
        )
        urgent = replace(
            proposal,
            proposal_id="urgent",
            deduplication_key="urgent",
            priority=100,
            can_preempt=True,
        )
        current = attention(16, visible=False)
        await controller.tick(
            attention=current,
            awareness=service.update(current),
            proposals=(urgent,),
            commands=commands,
        )
        donor, recipient = controller.snapshots()
        self.assertEqual(donor.status, MissionStatus.FAILED)
        self.assertEqual(recipient.status, MissionStatus.COMPLETED)
        self.assertIsNone(controller.allocator.owner_of(9000))
        self.assertEqual(donor.assigned_unit_tags, ())
        self.assertEqual(recipient.assigned_unit_tags, ())

    async def test_partial_loss_blocked_mission_times_out_and_releases_survivor(self):
        service = AwarenessService()
        current = attention(10, visible=False, reapers=2)
        awareness = service.update(current)
        proposal = replace(
            IntelPlanner().propose(current, awareness)[0],
            timeout_seconds=2,
            requirement=UnitRequirement(
                unit_types=frozenset({UnitTypeId.REAPER}),
                desired=2,
                minimum=2,
            ),
        )
        controller = MissionController(logger=FakeLogger(), executor_factories=DEFAULT_EXECUTOR_FACTORIES)
        commands = FakeCommands()
        for now, count in ((10, 2), (11, 1), (12, 1)):
            current = attention(now, visible=False, reapers=count)
            await controller.tick(
                attention=current,
                awareness=service.update(current),
                proposals=(proposal,) if now == 10 else (),
                commands=commands,
            )
            if now == 11:
                self.assertEqual(
                    controller.snapshots()[0].status, MissionStatus.BLOCKED
                )
        mission = controller.snapshots()[0]
        self.assertEqual(mission.status, MissionStatus.CANCELLED)
        self.assertEqual(mission.reason, "mission_timeout")
        self.assertEqual(mission.finished_at, 12)
        self.assertIsNone(controller.allocator.owner_of(9000))
        self.assertIn(("release", mission.mission_id, 9000), commands.commands)

    async def test_total_loss_is_not_hidden_by_an_available_replacement(self):
        service = AwarenessService()
        controller = MissionController(logger=FakeLogger(), executor_factories=DEFAULT_EXECUTOR_FACTORIES)
        commands = FakeCommands()
        current = attention(10, visible=False)
        awareness = service.update(current)
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=IntelPlanner().propose(current, awareness),
            commands=commands,
        )
        old = controller.snapshots()[0]
        current = replace(
            current,
            world=replace(
                current.world,
                time=11,
                own_units=tuple(
                    u
                    for u in current.world.own_units
                    if u.tag not in old.assigned_unit_tags
                )
                + (reaper(9999),),
            ),
        )
        await controller.tick(
            attention=current,
            awareness=service.update(current),
            proposals=(),
            commands=commands,
        )
        self.assertEqual(controller.snapshots()[0].reason, "all_assigned_units_lost")
        self.assertEqual(controller.snapshots()[0].status, MissionStatus.FAILED)
        self.assertIsNone(controller.allocator.owner_of(9999))

    async def test_partial_loss_blocks_below_minimum_and_resumes_with_replacement(self):
        for minimum in (1, 2):
            with self.subTest(minimum=minimum):
                service = AwarenessService()
                controller = MissionController(logger=FakeLogger(), executor_factories=DEFAULT_EXECUTOR_FACTORIES)
                commands = FakeCommands()
                current = attention(10, visible=False, reapers=2)
                awareness = service.update(current)
                proposal = replace(
                    IntelPlanner().propose(current, awareness)[0],
                    requirement=UnitRequirement(
                        unit_types=frozenset({UnitTypeId.REAPER}),
                        desired=2,
                        minimum=minimum,
                    ),
                )
                await controller.tick(
                    attention=current,
                    awareness=awareness,
                    proposals=(proposal,),
                    commands=commands,
                )
                commands.commands.clear()
                current = attention(11, visible=False, reapers=1)
                await controller.tick(
                    attention=current,
                    awareness=service.update(current),
                    proposals=(),
                    commands=commands,
                )
                mission = controller.snapshots()[0]
                self.assertEqual(mission.assigned_unit_tags, (9000,))
                self.assertEqual(
                    mission.status,
                    MissionStatus.ACTIVE if minimum == 1 else MissionStatus.BLOCKED,
                )
                self.assertEqual(bool(commands.commands), minimum == 1)
                current = attention(12, visible=False, reapers=2)
                await controller.tick(
                    attention=current,
                    awareness=service.update(current),
                    proposals=(),
                    commands=commands,
                )
                self.assertEqual(controller.snapshots()[0].status, MissionStatus.ACTIVE)
                self.assertEqual(controller.snapshots()[0].started_at, 10)

    async def test_terminal_outcomes_restore_roles_and_release_once(self):
        from ares.consts import UnitRole

        for outcome in ("completed", "timeout", "error"):
            for unit_type, role in (
                (UnitTypeId.SCV, UnitRole.GATHERING),
                (UnitTypeId.REAPER, UnitRole.IDLE),
            ):
                with self.subTest(outcome=outcome, unit_type=unit_type):
                    logger = FakeLogger()
                    controller = MissionController(logger=logger, executor_factories=DEFAULT_EXECUTOR_FACTORIES)
                    service = AwarenessService()
                    current = attention(10, visible=False)
                    awareness = service.update(current)
                    proposal = replace(
                        IntelPlanner().propose(current, awareness)[0],
                        timeout_seconds=1,
                        requirement=UnitRequirement(
                            unit_types=frozenset({unit_type}),
                            desired=1,
                            minimum=1,
                        ),
                    )
                    bot = SimpleNamespace(
                        worker_type=UnitTypeId.SCV,
                        unit_tag_dict={
                            u.tag: SimpleNamespace(type_id=u.unit_type)
                            for u in current.world.own_units
                        },
                        mediator=Mock(),
                    )
                    commands = AresMissionCommands(bot, controller.allocator)
                    commands.path_to = Mock()
                    if outcome == "error":
                        commands.path_to.side_effect = RuntimeError("path failed")
                    await controller.tick(
                        attention=current,
                        awareness=awareness,
                        proposals=(proposal,),
                        commands=commands,
                    )
                    current = attention(
                        10.5 if outcome == "completed" else 11,
                        visible=outcome == "completed",
                    )
                    for _ in range(2):
                        await controller.tick(
                            attention=current,
                            awareness=service.update(current),
                            proposals=(),
                            commands=commands,
                        )
                    mission = controller.snapshots()[0]
                    expected = {
                        "completed": MissionStatus.COMPLETED,
                        "timeout": MissionStatus.CANCELLED,
                        "error": MissionStatus.FAILED,
                    }[outcome]
                    self.assertEqual(mission.status, expected)
                    self.assertEqual(mission.assigned_unit_tags, ())
                    self.assertEqual(
                        controller.allocator.assigned_tags(mission.mission_id), ()
                    )
                    bot.mediator.assign_role.assert_called_once()
                    self.assertEqual(
                        bot.mediator.assign_role.call_args.kwargs["role"], role
                    )
                    self.assertTrue(all(e["data"]["reason"] for e in logger.events))

    async def test_preemption_finishes_donor_and_resets_role_before_new_executor(self):
        service = AwarenessService()
        logger = FakeLogger()
        controller = MissionController(logger=logger, executor_factories=DEFAULT_EXECUTOR_FACTORIES)
        commands = FakeCommands()
        current = attention(10, visible=False)
        awareness = service.update(current)
        proposal = IntelPlanner().propose(current, awareness)[0]
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=(proposal,),
            commands=commands,
        )
        donor = controller.snapshots()[0]
        tag = donor.assigned_unit_tags[0]
        urgent = replace(
            proposal,
            proposal_id="urgent",
            deduplication_key="urgent",
            priority=100,
            can_preempt=True,
        )
        current = attention(16, visible=False)
        commands.commands.clear()
        await controller.tick(
            attention=current,
            awareness=service.update(current),
            proposals=(urgent,),
            commands=commands,
        )
        donor, recipient = controller.snapshots()
        self.assertEqual(donor.reason, "all_assigned_units_preempted")
        self.assertEqual(donor.status, MissionStatus.FAILED)
        self.assertEqual(donor.assigned_unit_tags, ())
        self.assertEqual(recipient.status, MissionStatus.ACTIVE)
        self.assertEqual(controller.allocator.owner_of(tag), recipient.mission_id)
        self.assertEqual(commands.commands[0], ("release", recipient.mission_id, tag))
        self.assertEqual(commands.commands[1][0], "path_to")
        self.assertTrue(all(e["data"]["reason"] for e in logger.events))

    async def test_second_proposal_for_live_objective_is_rejected(self):
        logger = FakeLogger()
        commands = FakeCommands()
        service = AwarenessService()
        planner = IntelPlanner()
        current = attention(10.0, visible=False)
        awareness = service.update(current)
        first = planner.propose(current, awareness)[0]
        duplicate = replace(first, proposal_id=f"{first.proposal_id}:duplicate")
        controller = MissionController(logger=logger, executor_factories=DEFAULT_EXECUTOR_FACTORIES)

        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=(first, duplicate),
            commands=commands,
        )

        self.assertEqual(len(controller.snapshots()), 1)
        rejection = next(
            event for event in logger.events if event["name"] == "proposal_rejected"
        )
        self.assertEqual(rejection["data"]["reason"], "matching_mission_already_live")

    async def test_unknown_location_flows_to_completed_mission_and_release(self):
        logger = FakeLogger()
        commands = FakeCommands()
        awareness_service = AwarenessService(location_stale_after=90.0)
        planner = IntelPlanner()
        controller = MissionController(logger=logger, executor_factories=DEFAULT_EXECUTOR_FACTORIES)

        first_attention = attention(10.0, visible=False)
        first_awareness = awareness_service.update(first_attention)
        proposals = planner.propose(first_attention, first_awareness)
        await controller.tick(
            attention=first_attention,
            awareness=first_awareness,
            proposals=proposals,
            commands=commands,
        )

        active = controller.snapshots()[0]
        self.assertNotEqual(active.proposal_id, active.mission_id)
        self.assertEqual(active.status, MissionStatus.ACTIVE)
        self.assertEqual(commands.commands[0][0], "path_to")

        refreshed_attention = attention(11.0, visible=True)
        refreshed_awareness = awareness_service.update(refreshed_attention)
        await controller.tick(
            attention=refreshed_attention,
            awareness=refreshed_awareness,
            proposals=planner.propose(refreshed_attention, refreshed_awareness),
            commands=commands,
        )

        completed = controller.snapshots()[0]
        self.assertEqual(completed.status, MissionStatus.COMPLETED)
        self.assertEqual(completed.reason, "target_observed_after_mission_started")
        self.assertEqual(completed.assigned_unit_tags, ())
        self.assertIsNone(controller.allocator.owner_of(active.assigned_unit_tags[0]))

        names = [event["name"] for event in logger.events]
        self.assertEqual(
            names[:5],
            [
                "proposal_created",
                "proposal_admitted",
                "mission_queued",
                "units_assigned",
                "mission_started",
            ],
        )
        self.assertIn("units_released", names)
        self.assertIn("mission_completed", names)
        for event in logger.events:
            if event["name"].startswith(("proposal_", "mission_")):
                self.assertTrue(event["data"]["reason"])

    async def test_admitted_mission_is_blocked_without_an_eligible_unit(self):
        logger = FakeLogger()
        commands = FakeCommands()
        awareness_service = AwarenessService()
        planner = IntelPlanner()

        # Create the proposal with a healthy economy, then expose no eligible units
        # to the controller. Planner and allocator remain distinct responsibilities.
        rich_attention = attention(10.0, visible=False)
        awareness = awareness_service.update(rich_attention)
        proposal = planner.propose(rich_attention, awareness)
        empty_attention = attention(10.0, visible=False, workers=0, reapers=0)
        controller = MissionController(logger=logger, executor_factories=DEFAULT_EXECUTOR_FACTORIES)
        await controller.tick(
            attention=empty_attention,
            awareness=awareness,
            proposals=proposal,
            commands=commands,
        )

        self.assertEqual(controller.snapshots()[0].status, MissionStatus.BLOCKED)
        self.assertEqual(commands.commands, [])
        self.assertIn("mission_blocked", [event["name"] for event in logger.events])

    async def test_executor_error_fails_and_releases_the_mission(self):
        class FailingCommands(FakeCommands):
            def path_to(self, **kwargs) -> None:
                raise RuntimeError("path unavailable")

        logger = FakeLogger()
        commands = FailingCommands()
        service = AwarenessService()
        planner = IntelPlanner()
        current = attention(10.0, visible=False)
        awareness = service.update(current)
        controller = MissionController(logger=logger, executor_factories=DEFAULT_EXECUTOR_FACTORIES)

        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=planner.propose(current, awareness),
            commands=commands,
        )

        mission = controller.snapshots()[0]
        self.assertEqual(mission.status, MissionStatus.FAILED)
        self.assertIn("executor_error:RuntimeError", mission.reason)
        self.assertEqual(mission.assigned_unit_tags, ())
        self.assertIn("mission_failed", [event["name"] for event in logger.events])

    async def test_active_mission_fails_fast_when_all_assigned_units_are_lost(self):
        logger = FakeLogger()
        commands = FakeCommands()
        service = AwarenessService()
        planner = IntelPlanner()
        current = attention(10.0, visible=False, reapers=1)
        awareness = service.update(current)
        controller = MissionController(logger=logger, executor_factories=DEFAULT_EXECUTOR_FACTORIES)

        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=planner.propose(current, awareness),
            commands=commands,
        )

        active = controller.snapshots()[0]
        self.assertEqual(active.status, MissionStatus.ACTIVE)

        unit_lost_attention = attention(11.0, visible=False, reapers=0)
        unit_lost_awareness = service.update(unit_lost_attention)
        await controller.tick(
            attention=unit_lost_attention,
            awareness=unit_lost_awareness,
            proposals=(),
            commands=commands,
        )

        failed = controller.snapshots()[0]
        self.assertEqual(failed.status, MissionStatus.FAILED)
        self.assertEqual(failed.reason, "all_assigned_units_lost")
        self.assertEqual(failed.assigned_unit_tags, ())
        self.assertIn("mission_failed", [event["name"] for event in logger.events])

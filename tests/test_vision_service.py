from __future__ import annotations

import unittest
from unittest.mock import Mock

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.adapters.ares import AresVisionCommands
from bot.engine.services import (
    ScanProvider,
    VisionRequestStatus,
    VisionService,
    VisionUrgency,
)
from bot.world.attention import (
    AttentionSnapshot,
    MapFacts,
    UnitSnapshot,
    WorldFacts,
)
from tests.fakes import FakeLogger

MAIN = Point2((90, 90))
NATURAL = Point2((80, 80))


class FakeVisionCommands:
    def __init__(
        self, *, visible: tuple[Point2, ...] = (), accepted: bool = True
    ) -> None:
        self.visible = visible
        self.accepted = accepted
        self.commands: list[tuple] = []

    def has_vision(self, position: Point2) -> bool:
        return position in self.visible

    def scan(self, *, orbital_tag: int, target: Point2) -> bool:
        self.commands.append(("scan", orbital_tag, target))
        return self.accepted


def orbital(tag: int, energy: float) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.ORBITALCOMMAND,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=False,
        is_structure=True,
        energy=energy,
    )


def attention(
    now: float, *, orbitals: tuple[UnitSnapshot, ...] = ()
) -> AttentionSnapshot:
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=0,
            supply_cap=15,
            own_units=(),
            enemy_units=(),
            own_structures=orbitals,
            map=MapFacts(
                center=Point2((50, 50)),
                own_start=Point2((10, 10)),
                enemy_starts=(MAIN,),
            ),
        )
    )


def request(
    service: VisionService,
    position: Point2 = MAIN,
    *,
    urgency: VisionUrgency = VisionUrgency.NORMAL,
    requester: str = "scouting",
):
    return service.request(
        position=position,
        urgency=urgency,
        requester=requester,
        reason="information_stale",
        ttl=12.0,
    )


class VisionServiceTests(unittest.TestCase):
    def test_request_moves_from_pending_to_satisfied_when_vision_arrives(self):
        service = VisionService()
        commands = FakeVisionCommands()
        service.begin_frame(attention(120.0, orbitals=(orbital(7, 100.0),)), commands)

        created = request(service)
        service.resolve()

        self.assertEqual(created.status, VisionRequestStatus.PENDING)
        self.assertEqual(commands.commands, [("scan", 7, MAIN)])
        self.assertEqual(
            service.result(created.request_id).status, VisionRequestStatus.PENDING
        )

        visible = FakeVisionCommands(visible=(MAIN,))
        service.begin_frame(attention(121.0, orbitals=(orbital(7, 50.0),)), visible)

        self.assertEqual(
            service.result(created.request_id).status,
            VisionRequestStatus.SATISFIED,
        )

    def test_insufficient_energy_reports_unavailable_without_command(self):
        service = VisionService()
        commands = FakeVisionCommands()
        service.begin_frame(attention(120.0, orbitals=(orbital(7, 99.0),)), commands)
        created = request(service)

        service.resolve()

        result = service.result(created.request_id)
        self.assertEqual(result.status, VisionRequestStatus.UNAVAILABLE)
        self.assertEqual(result.reason, "insufficient_orbital_energy")
        self.assertEqual(commands.commands, [])

    def test_unavailable_request_logs_are_rate_limited_across_frames(self):
        logger = FakeLogger()
        service = VisionService(logger=logger)
        commands = FakeVisionCommands()
        service.begin_frame(attention(120.0, orbitals=(orbital(7, 50.0),)), commands)
        request(service)
        service.resolve()
        service.begin_frame(attention(121.0, orbitals=(orbital(7, 51.0),)), commands)
        service.resolve()

        names = [event["name"] for event in logger.events]
        self.assertEqual(names.count("vision.request_selected"), 1)
        self.assertEqual(names.count("vision.request_deferred"), 1)

    def test_higher_urgency_request_wins_arbitration(self):
        service = VisionService()
        commands = FakeVisionCommands()
        service.begin_frame(attention(120.0, orbitals=(orbital(7, 150.0),)), commands)
        request(service, MAIN, urgency=VisionUrgency.NORMAL, requester="scouting")
        request(service, NATURAL, urgency=VisionUrgency.HIGH, requester="defense")

        service.resolve()

        self.assertEqual(commands.commands, [("scan", 7, NATURAL)])

    def test_spatially_close_requests_are_deduplicated(self):
        logger = FakeLogger()
        service = VisionService(logger=logger)
        service.begin_frame(attention(120.0), FakeVisionCommands())

        first = request(service, MAIN, requester="scouting")
        duplicate = request(
            service,
            Point2((94, 90)),
            urgency=VisionUrgency.HIGH,
            requester="defense",
        )

        self.assertEqual(first.request_id, duplicate.request_id)
        self.assertEqual(
            [event["name"] for event in logger.events].count(
                "vision.request_deduplicated"
            ),
            1,
        )

    def test_a_request_repeated_each_frame_does_not_repeat_the_scan(self):
        service = VisionService()
        first_commands = FakeVisionCommands()
        service.begin_frame(
            attention(120.0, orbitals=(orbital(7, 200.0),)), first_commands
        )
        first = request(service)
        service.resolve()

        second_commands = FakeVisionCommands()
        service.begin_frame(
            attention(121.0, orbitals=(orbital(7, 150.0),)), second_commands
        )
        duplicate = request(service)
        service.resolve()

        self.assertEqual(first.request_id, duplicate.request_id)
        self.assertEqual(len(first_commands.commands), 1)
        self.assertEqual(second_commands.commands, [])

    def test_provider_uses_fullest_orbital_and_preserves_reserve(self):
        service = VisionService(provider=ScanProvider())
        commands = FakeVisionCommands()
        service.begin_frame(
            attention(
                120.0,
                orbitals=(orbital(1, 99.0), orbital(2, 110.0), orbital(3, 150.0)),
            ),
            commands,
        )

        request(service)
        service.resolve()

        self.assertEqual(commands.commands, [("scan", 3, MAIN)])

    def test_logs_request_selection_provider_execution_and_satisfaction(self):
        logger = FakeLogger()
        provider = ScanProvider(logger=logger)
        service = VisionService(provider=provider, logger=logger)
        commands = FakeVisionCommands()
        service.begin_frame(attention(120.0, orbitals=(orbital(7, 100.0),)), commands)
        created = request(service)
        service.resolve()
        service.begin_frame(
            attention(121.0, orbitals=(orbital(7, 50.0),)),
            FakeVisionCommands(visible=(MAIN,)),
        )

        names = [event["name"] for event in logger.events]
        self.assertIn("vision.request_created", names)
        self.assertIn("vision.request_selected", names)
        self.assertIn("vision.provider_selected", names)
        self.assertIn("vision.scan_executed", names)
        self.assertIn("vision.request_satisfied", names)
        satisfied = next(
            event
            for event in logger.events
            if event["name"] == "vision.request_satisfied"
        )
        self.assertEqual(satisfied["data"]["request_id"], created.request_id)


class AresVisionCommandsTests(unittest.TestCase):
    def test_casts_scanner_sweep_at_the_provider_selected_position(self):
        unit = Mock()
        unit.type_id = UnitTypeId.ORBITALCOMMAND
        unit.is_ready = True
        unit.abilities = {AbilityId.SCANNERSWEEP_SCAN}
        bot = Mock()
        bot.unit_tag_dict = {7: unit}
        bot.config = {}

        accepted = AresVisionCommands(bot).scan(orbital_tag=7, target=MAIN)

        self.assertTrue(accepted)
        unit.assert_called_once_with(AbilityId.SCANNERSWEEP_SCAN, MAIN)

    def test_visibility_query_uses_the_game_adapter(self):
        bot = Mock()
        bot.is_visible.return_value = True

        self.assertTrue(AresVisionCommands(bot).has_vision(MAIN))
        bot.is_visible.assert_called_once_with(MAIN)


if __name__ == "__main__":
    unittest.main()

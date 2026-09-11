from __future__ import annotations

import unittest
from unittest.mock import Mock

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.adapters.ares import AresScoutingCommands
from bot.behavior.scouting import MainBaseScanBehavior, ScanConfig
from bot.world.attention import (
    AttentionSnapshot,
    MapFacts,
    MapObservation,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness import AwarenessService
from tests.fakes import FakeLogger

TARGET = Point2((90, 90))


class FakeScoutingCommands:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.commands: list[tuple] = []

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
    now: float,
    *,
    visible: bool = False,
    orbitals: tuple[UnitSnapshot, ...] = (),
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
                enemy_starts=(TARGET,),
                observations=(MapObservation("enemy_main", TARGET, visible),),
            ),
        )
    )


class MainBaseScanBehaviorTests(unittest.TestCase):
    def test_scans_an_enemy_main_unseen_for_two_minutes(self):
        observed = attention(120.0, orbitals=(orbital(7, 100.0),))
        awareness = AwarenessService().update(observed)
        commands = FakeScoutingCommands()
        behavior = MainBaseScanBehavior()

        accepted = behavior.tick(observed, awareness, commands)

        self.assertTrue(accepted)
        self.assertEqual(commands.commands, [("scan", 7, TARGET)])
        self.assertEqual(behavior.last_plan.reason, "enemy_main_vision_stale")

    def test_waits_until_vision_has_been_missing_long_enough(self):
        observed = attention(119.9, orbitals=(orbital(7, 200.0),))
        awareness = AwarenessService().update(observed)
        commands = FakeScoutingCommands()

        self.assertFalse(MainBaseScanBehavior().tick(observed, awareness, commands))
        self.assertEqual(commands.commands, [])

    def test_age_is_measured_from_the_last_real_vision(self):
        service = AwarenessService()
        service.update(attention(50.0, visible=True))
        too_soon = attention(169.0, orbitals=(orbital(7, 100.0),))
        stale = attention(170.0, orbitals=(orbital(7, 100.0),))
        behavior = MainBaseScanBehavior()
        commands = FakeScoutingCommands()

        self.assertFalse(behavior.tick(too_soon, service.update(too_soon), commands))
        self.assertTrue(behavior.tick(stale, service.update(stale), commands))
        self.assertEqual(len(commands.commands), 1)

    def test_preserves_fifty_energy_and_uses_the_fullest_orbital(self):
        observed = attention(
            120.0,
            orbitals=(orbital(1, 99.9), orbital(2, 110.0), orbital(3, 150.0)),
        )
        awareness = AwarenessService().update(observed)
        commands = FakeScoutingCommands()

        MainBaseScanBehavior().tick(observed, awareness, commands)

        self.assertEqual(commands.commands, [("scan", 3, TARGET)])

    def test_current_vision_suppresses_the_scan(self):
        observed = attention(500.0, visible=True, orbitals=(orbital(7, 200.0),))
        awareness = AwarenessService().update(observed)
        commands = FakeScoutingCommands()

        self.assertFalse(MainBaseScanBehavior().tick(observed, awareness, commands))
        self.assertEqual(commands.commands, [])

    def test_post_scan_cooldown_avoids_a_duplicate_before_vision_updates(self):
        config = ScanConfig(max_without_vision=10.0, post_scan_cooldown=15.0)
        behavior = MainBaseScanBehavior(config=config)
        service = AwarenessService()
        commands = FakeScoutingCommands()
        first = attention(10.0, orbitals=(orbital(7, 200.0),))
        next_frame = attention(11.0, orbitals=(orbital(7, 150.0),))

        self.assertTrue(behavior.tick(first, service.update(first), commands))
        self.assertFalse(
            behavior.tick(next_frame, service.update(next_frame), commands)
        )
        self.assertEqual(len(commands.commands), 1)

    def test_logs_dispatch_with_the_selected_orbital(self):
        logger = FakeLogger()
        observed = attention(120.0, orbitals=(orbital(7, 100.0),))
        awareness = AwarenessService().update(observed)

        MainBaseScanBehavior(logger=logger).tick(
            observed, awareness, FakeScoutingCommands()
        )

        event = next(
            item
            for item in logger.events
            if item["name"] == "behavior.state_changed"
        )
        self.assertEqual(event["component"], "behavior.scouting.scan")
        self.assertEqual(event["data"]["state"], "scan_dispatched")
        self.assertEqual(event["data"]["orbital_tag"], 7)


class AresScoutingCommandsTests(unittest.TestCase):
    def test_casts_scanner_sweep_at_the_requested_position(self):
        unit = Mock()
        unit.type_id = UnitTypeId.ORBITALCOMMAND
        unit.is_ready = True
        unit.abilities = {AbilityId.SCANNERSWEEP_SCAN}
        bot = Mock()
        bot.unit_tag_dict = {7: unit}
        bot.config = {}

        accepted = AresScoutingCommands(bot).scan(orbital_tag=7, target=TARGET)

        self.assertTrue(accepted)
        unit.assert_called_once_with(AbilityId.SCANNERSWEEP_SCAN, TARGET)

    def test_rejects_a_non_orbital_tag(self):
        unit = Mock()
        unit.type_id = UnitTypeId.COMMANDCENTER
        bot = Mock()
        bot.unit_tag_dict = {7: unit}

        self.assertFalse(AresScoutingCommands(bot).scan(orbital_tag=7, target=TARGET))
        unit.assert_not_called()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.harass import HarassPlanner
from bot.engine.missions import MissionKind
from bot.world.attention import (
    AttentionSnapshot,
    MapFacts,
    MapObservation,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness import AwarenessService

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


def reaper(tag: int, *, available: bool = True) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.REAPER,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
        available_for_mission=available,
    )


def enemy_marine(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=Point2((50, 50)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
        visible_now=True,
    )


def enemy_anti_air(tag: int, *, position: Point2 = TARGET) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
        visible_now=True,
    )


def banshee(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.BANSHEE,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=True,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
    )


def attention(
    time: float,
    *,
    natural_visible: bool,
    workers: int = 16,
    reapers: int = 1,
    banshees: int = 0,
    visible_enemies: int = 0,
    reaper_available: bool = True,
    anti_air_enemies: tuple[UnitSnapshot, ...] = (),
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
            *(
                reaper(9000 + tag, available=reaper_available)
                for tag in range(reapers)
            ),
            *(banshee(9500 + tag) for tag in range(banshees)),
        ),
        enemy_units=(
            *(enemy_marine(8000 + tag) for tag in range(visible_enemies)),
            *anti_air_enemies,
        ),
        map=MapFacts(
            center=Point2((50, 50)),
            own_start=Point2((10, 10)),
            enemy_starts=(Point2((90, 90)),),
            observations=(MapObservation("enemy_natural", TARGET, natural_visible),),
        ),
    )
    return AttentionSnapshot(world)


class ReaperHarassTests(unittest.TestCase):
    def test_no_proposal_when_target_was_never_observed(self):
        current = attention(10.0, natural_visible=False)
        awareness = AwarenessService().update(current)

        self.assertEqual(HarassPlanner().propose(current, awareness), ())

    def test_visible_defenders_do_not_suppress_aggressive_harass(self):
        service = AwarenessService()
        service.update(attention(10.0, natural_visible=True))
        current = attention(20.0, natural_visible=False, visible_enemies=1)
        awareness = service.update(current)

        proposals = HarassPlanner().propose(current, awareness)
        self.assertEqual([p.kind for p in proposals], [MissionKind.HARASS])

    def test_no_proposal_below_the_economic_gate(self):
        service = AwarenessService()
        service.update(attention(10.0, natural_visible=True, workers=10))
        current = attention(20.0, natural_visible=False, workers=10)
        awareness = service.update(current)

        self.assertEqual(HarassPlanner().propose(current, awareness), ())

    def test_no_proposal_without_a_harass_capable_unit_alive(self):
        service = AwarenessService()
        service.update(attention(10.0, natural_visible=True, reapers=0))
        current = attention(20.0, natural_visible=False, reapers=0)
        awareness = service.update(current)

        self.assertEqual(HarassPlanner().propose(current, awareness), ())

    def test_no_proposal_while_the_only_reaper_is_busy(self):
        service = AwarenessService()
        service.update(attention(10.0, natural_visible=True))
        current = attention(
            20.0,
            natural_visible=False,
            reaper_available=False,
        )
        awareness = service.update(current)

        self.assertEqual(HarassPlanner().propose(current, awareness), ())

    def test_proposes_worker_line_harass_once_target_is_known_and_undefended(self):
        service = AwarenessService()
        service.update(attention(10.0, natural_visible=True))
        current = attention(20.0, natural_visible=False)
        awareness = service.update(current)

        proposals = HarassPlanner().propose(current, awareness)

        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.kind, MissionKind.HARASS)
        self.assertEqual(proposal.target, TARGET)
        self.assertEqual(proposal.target_key, "enemy_natural")
        self.assertEqual(proposal.deduplication_key, "harass:enemy_natural")
        self.assertTrue(proposal.reason.strip())
        self.assertTrue(proposal.proposal_id.strip())
        self.assertTrue(0 <= proposal.priority <= 100)
        self.assertGreater(proposal.timeout_seconds, 0.0)
        self.assertGreaterEqual(proposal.cooldown_seconds, 0.0)
        self.assertFalse(proposal.can_preempt)
        self.assertEqual(
            proposal.requirement.unit_types, frozenset({UnitTypeId.REAPER})
        )
        self.assertEqual(proposal.requirement.desired, 1)
        self.assertEqual(proposal.requirement.minimum, 1)
        self.assertTrue(proposal.requirement.exclude_resource_carriers)
        self.assertTrue(proposal.requirement.exclude_constructors)

    def test_respects_its_proposal_cadence(self):
        service = AwarenessService()
        service.update(attention(10.0, natural_visible=True))
        planner = HarassPlanner()
        first = attention(20.0, natural_visible=False)
        self.assertEqual(len(planner.propose(first, service.update(first))), 1)

        second = attention(21.0, natural_visible=False)
        self.assertEqual(planner.propose(second, service.update(second)), ())


class BansheeHarassTests(unittest.TestCase):
    def test_no_proposal_when_target_was_never_observed(self):
        current = attention(10.0, natural_visible=False, reapers=0, banshees=1)
        awareness = AwarenessService().update(current)

        self.assertEqual(HarassPlanner().propose(current, awareness), ())

    def test_no_proposal_while_an_anti_air_unit_is_near_the_target(self):
        service = AwarenessService()
        service.update(
            attention(10.0, natural_visible=True, reapers=0, banshees=1)
        )
        current = attention(
            20.0,
            natural_visible=False,
            reapers=0,
            banshees=1,
            anti_air_enemies=(enemy_anti_air(8500, position=TARGET),),
        )
        awareness = service.update(current)

        proposals = HarassPlanner().propose(current, awareness)
        self.assertEqual([p.kind for p in proposals], [])

    def test_an_anti_air_unit_far_from_the_target_does_not_withhold(self):
        # The gate scopes anti-air safety to near the harass target, not the
        # whole map -- an enemy army sitting anywhere else in vision (as is
        # true in nearly every real game past the early minutes) must not
        # permanently ground every Banshee raid.
        service = AwarenessService()
        service.update(
            attention(10.0, natural_visible=True, reapers=0, banshees=1)
        )
        current = attention(
            20.0,
            natural_visible=False,
            reapers=0,
            banshees=1,
            anti_air_enemies=(enemy_anti_air(8500, position=Point2((10, 90))),),
        )
        awareness = service.update(current)

        proposals = HarassPlanner().propose(current, awareness)
        self.assertEqual([p.kind for p in proposals], [MissionKind.AIR_HARASS])

    def test_a_non_anti_air_enemy_near_the_target_does_not_withhold(self):
        # A ground defender that cannot hit air is not a reason to withhold a
        # flying, cloaked harasser.
        service = AwarenessService()
        service.update(
            attention(10.0, natural_visible=True, reapers=0, banshees=1)
        )
        current = attention(
            20.0,
            natural_visible=False,
            reapers=0,
            banshees=1,
            visible_enemies=1,
        )
        awareness = service.update(current)

        proposals = HarassPlanner().propose(current, awareness)
        self.assertEqual([p.kind for p in proposals], [MissionKind.AIR_HARASS])

    def test_no_proposal_below_the_economic_gate(self):
        service = AwarenessService()
        service.update(
            attention(
                10.0, natural_visible=True, reapers=0, banshees=1, workers=6
            )
        )
        current = attention(
            20.0, natural_visible=False, reapers=0, banshees=1, workers=6
        )
        awareness = service.update(current)

        proposals = HarassPlanner().propose(current, awareness)
        self.assertEqual([p.kind for p in proposals], [])

    def test_no_proposal_without_a_banshee_alive(self):
        service = AwarenessService()
        service.update(attention(10.0, natural_visible=True, reapers=0, banshees=0))
        current = attention(20.0, natural_visible=False, reapers=0, banshees=0)
        awareness = service.update(current)

        proposals = HarassPlanner().propose(current, awareness)
        self.assertEqual([p.kind for p in proposals], [])

    def test_proposes_air_harass_once_target_is_known_and_undefended(self):
        service = AwarenessService()
        service.update(
            attention(10.0, natural_visible=True, reapers=0, banshees=1)
        )
        current = attention(20.0, natural_visible=False, reapers=0, banshees=1)
        awareness = service.update(current)

        proposals = [
            p
            for p in HarassPlanner().propose(current, awareness)
            if p.kind is MissionKind.AIR_HARASS
        ]

        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.kind, MissionKind.AIR_HARASS)
        self.assertEqual(proposal.target, TARGET)
        self.assertEqual(proposal.target_key, "enemy_natural")
        self.assertEqual(proposal.deduplication_key, "air_harass:enemy_natural")
        self.assertFalse(proposal.can_preempt)
        self.assertEqual(
            proposal.requirement.unit_types, frozenset({UnitTypeId.BANSHEE})
        )


class CombinedHarassTests(unittest.TestCase):
    def test_reaper_and_banshee_raids_can_both_be_live_at_once(self):
        service = AwarenessService()
        service.update(
            attention(10.0, natural_visible=True, reapers=1, banshees=1)
        )
        current = attention(20.0, natural_visible=False, reapers=1, banshees=1)
        awareness = service.update(current)

        proposals = HarassPlanner().propose(current, awareness)

        self.assertEqual(
            sorted(p.kind.name for p in proposals),
            sorted([MissionKind.HARASS.name, MissionKind.AIR_HARASS.name]),
        )


if __name__ == "__main__":
    unittest.main()

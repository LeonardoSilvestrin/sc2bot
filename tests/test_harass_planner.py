from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.harass import BansheeHarassPlanner, HarassPlanner
from bot.engine.missions import MissionKind
from bot.world.knowledge import AwarenessService
from bot.world.observation.models import (
    AttentionSnapshot,
    MapFacts,
    MapObservation,
    UnitSnapshot,
    WorldFacts,
)

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


def enemy_anti_air(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=Point2((50, 50)),
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
<<<<<<< HEAD
    reaper_available: bool = True,
=======
    visible_anti_air_enemies: int = 0,
>>>>>>> agents/claude
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
<<<<<<< HEAD
            *(reaper(9000 + tag, available=reaper_available) for tag in range(reapers)),
=======
            *(reaper(9000 + tag) for tag in range(reapers)),
            *(banshee(9500 + tag) for tag in range(banshees)),
        ),
        enemy_units=(
            *(enemy_marine(8000 + tag) for tag in range(visible_enemies)),
            *(
                enemy_anti_air(8500 + tag)
                for tag in range(visible_anti_air_enemies)
            ),
>>>>>>> agents/claude
        ),
        map=MapFacts(
            center=Point2((50, 50)),
            own_start=Point2((10, 10)),
            enemy_starts=(Point2((90, 90)),),
            observations=(MapObservation("enemy_natural", TARGET, natural_visible),),
        ),
    )
    return AttentionSnapshot(world)


class HarassPlannerTests(unittest.TestCase):
    def test_no_proposal_when_target_was_never_observed(self):
        current = attention(10.0, natural_visible=False)
        awareness = AwarenessService().update(current)

        self.assertEqual(HarassPlanner().propose(current, awareness), ())

    def test_visible_defenders_do_not_suppress_aggressive_harass(self):
        service = AwarenessService()
        service.update(attention(10.0, natural_visible=True))
        current = attention(20.0, natural_visible=False, visible_enemies=1)
        awareness = service.update(current)

        self.assertEqual(len(HarassPlanner().propose(current, awareness)), 1)

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


class BansheeHarassPlannerTests(unittest.TestCase):
    def test_no_proposal_when_target_was_never_observed(self):
        current = attention(10.0, natural_visible=False, reapers=0, banshees=1)
        awareness = AwarenessService().update(current)

        self.assertEqual(BansheeHarassPlanner().propose(current, awareness), ())

    def test_no_proposal_while_an_anti_air_unit_is_visible(self):
        service = AwarenessService()
        service.update(
            attention(10.0, natural_visible=True, reapers=0, banshees=1)
        )
        current = attention(
            20.0,
            natural_visible=False,
            reapers=0,
            banshees=1,
            visible_anti_air_enemies=1,
        )
        awareness = service.update(current)

        self.assertEqual(BansheeHarassPlanner().propose(current, awareness), ())

    def test_a_non_anti_air_enemy_does_not_withhold_the_proposal(self):
        # Unlike `HarassPlanner`, a ground defender that cannot hit air is not
        # a reason to withhold a flying, cloaked harasser.
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

        self.assertEqual(len(BansheeHarassPlanner().propose(current, awareness)), 1)

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

        self.assertEqual(BansheeHarassPlanner().propose(current, awareness), ())

    def test_no_proposal_without_a_banshee_alive(self):
        service = AwarenessService()
        service.update(attention(10.0, natural_visible=True, reapers=0, banshees=0))
        current = attention(20.0, natural_visible=False, reapers=0, banshees=0)
        awareness = service.update(current)

        self.assertEqual(BansheeHarassPlanner().propose(current, awareness), ())

    def test_proposes_air_harass_once_target_is_known_and_undefended(self):
        service = AwarenessService()
        service.update(
            attention(10.0, natural_visible=True, reapers=0, banshees=1)
        )
        current = attention(20.0, natural_visible=False, reapers=0, banshees=1)
        awareness = service.update(current)

        proposals = BansheeHarassPlanner().propose(current, awareness)

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


if __name__ == "__main__":
    unittest.main()

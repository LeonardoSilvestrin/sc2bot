from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.army import DispositionPlanner
from bot.engine.missions import MissionKind, MissionMode
from bot.world.attention import AttentionSnapshot, MapFacts, UnitSnapshot, WorldFacts
from bot.world.awareness import AwarenessSnapshot, RelativeStrength, ThreatAssessment
from bot.world.awareness.bases import BaseSecurityAssessor
from bot.world.awareness.enemy import EnemyAwareness

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)


def unit(tag: int, unit_type: UnitTypeId = UnitTypeId.MARINE) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=unit_type,
        position=MAP.own_start,
        health_percentage=1.0,
        is_flying=unit_type is UnitTypeId.BANSHEE,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
    )


def townhall(tag: int, position: Point2) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.COMMANDCENTER,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=False,
        is_structure=True,
    )


def current(
    now: float,
    *,
    count: int = 10,
    bases: tuple[UnitSnapshot, ...] = (),
) -> tuple[AttentionSnapshot, AwarenessSnapshot]:
    attention = AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=float(count),
            supply_cap=200,
            own_units=tuple(unit(tag) for tag in range(1, count + 1)),
            enemy_units=(),
            map=MAP,
            own_structures=bases,
        )
    )
    awareness = AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, count, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=now,
        bases=BaseSecurityAssessor().update(attention.world),
    )
    return attention, awareness


class MainArmyDispositionTests(unittest.TestCase):
    def test_declares_one_persistent_main_army_at_eighty_percent(self):
        attention, awareness = current(10.0, count=10)

        proposals = DispositionPlanner().propose(attention, awareness)

        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.kind, MissionKind.HOLD_RALLY)
        self.assertEqual(proposal.mode, MissionMode.STANDING)
        self.assertEqual(proposal.squad_id, "main_army")
        self.assertEqual(proposal.deduplication_key, "hold_rally:main_army")
        self.assertEqual(proposal.requirement.desired, 8)
        self.assertEqual(proposal.requirement.minimum, 0)

    def test_rally_is_seventy_two_percent_from_previous_to_newest_base(self):
        main = townhall(100, MAP.own_start)
        natural = townhall(101, Point2((20, 20)))
        newest = townhall(102, Point2((40, 40)))
        attention, awareness = current(10.0, bases=(newest, main, natural))

        proposal = DispositionPlanner().propose(attention, awareness)[0]

        self.assertEqual(proposal.target, Point2((34.4, 34.4)))

    def test_banshees_are_left_for_the_specialized_persistent_squad(self):
        attention, awareness = current(10.0, count=5)
        attention = AttentionSnapshot(
            replace(
                attention.world,
                own_units=(*attention.world.own_units, unit(99, UnitTypeId.BANSHEE)),
            )
        )

        proposal = DispositionPlanner().propose(attention, awareness)[0]

        self.assertNotIn(UnitTypeId.BANSHEE, proposal.requirement.unit_types)
        self.assertEqual(proposal.requirement.desired, 4)

    def test_keeps_the_same_dedup_key_across_cadence_ticks(self):
        planner = DispositionPlanner()
        first, awareness = current(10.0)
        first_proposal = planner.propose(first, awareness)[0]
        second, awareness = current(16.0)
        second_proposal = planner.propose(second, awareness)[0]

        self.assertEqual(
            first_proposal.deduplication_key,
            second_proposal.deduplication_key,
        )
        self.assertEqual(planner.propose(second, awareness), ())


if __name__ == "__main__":
    unittest.main()

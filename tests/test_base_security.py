from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.world.attention import MapFacts, UnitSnapshot, WorldFacts
from bot.world.awareness.bases import BaseSecurityAssessor, BaseSecurityLevel

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
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


def marine(tag: int, position: Point2, *, own: bool = False) -> UnitSnapshot:
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


def world(
    *,
    own_structures: tuple[UnitSnapshot, ...] = (),
    own_units: tuple[UnitSnapshot, ...] = (),
    enemy_units: tuple[UnitSnapshot, ...] = (),
) -> WorldFacts:
    return WorldFacts(
        iteration=1,
        time=30.0,
        minerals=0,
        vespene=0,
        supply_used=0.0,
        supply_cap=0.0,
        own_units=own_units,
        enemy_units=enemy_units,
        map=MAP,
        own_structures=own_structures,
    )


class WorldFactsBasesTests(unittest.TestCase):
    def test_synthesizes_a_placeholder_base_before_any_townhall_is_observed(self):
        facts = world()

        self.assertEqual(len(facts.bases), 1)
        base = facts.bases[0]
        self.assertEqual(base.base_id, "own_base")
        self.assertEqual(base.position, MAP.own_start)
        self.assertTrue(base.is_main)
        self.assertIsNone(base.townhall)

    def test_one_base_per_owned_townhall(self):
        facts = world(
            own_structures=(
                townhall(1, MAP.own_start),
                townhall(2, Point2((40, 40))),
            )
        )

        self.assertEqual(len(facts.bases), 2)
        base_ids = {base.base_id for base in facts.bases}
        self.assertEqual(base_ids, {"base:1", "base:2"})
        main = next(base for base in facts.bases if base.base_id == "base:1")
        expansion = next(base for base in facts.bases if base.base_id == "base:2")
        self.assertTrue(main.is_main)
        self.assertFalse(expansion.is_main)


class BaseSecurityAssessorTests(unittest.TestCase):
    def test_base_with_no_enemies_nearby_is_safe(self):
        facts = world(own_structures=(townhall(1, MAP.own_start),))

        awareness = BaseSecurityAssessor().update(facts)

        self.assertEqual(len(awareness), 1)
        self.assertEqual(awareness.assessments[0].security, BaseSecurityLevel.SAFE)
        self.assertEqual(awareness.threatened, ())

    def test_undefended_base_under_attack_is_critical(self):
        facts = world(
            own_structures=(townhall(1, MAP.own_start),),
            enemy_units=(marine(50, Point2((12, 10))),),
        )

        awareness = BaseSecurityAssessor().update(facts)

        assessment = awareness.get("base:1")
        self.assertIsNotNone(assessment)
        self.assertEqual(assessment.security, BaseSecurityLevel.CRITICAL)
        self.assertEqual(assessment.nearest_threat_position, Point2((12, 10)))
        self.assertIn(assessment, awareness.threatened)

    def test_defended_base_under_attack_is_threatened_not_critical(self):
        facts = world(
            own_structures=(townhall(1, MAP.own_start),),
            own_units=(marine(1, Point2((10, 10))),),
            enemy_units=(marine(50, Point2((12, 10))),),
        )

        awareness = BaseSecurityAssessor().update(facts)

        assessment = awareness.get("base:1")
        self.assertEqual(assessment.security, BaseSecurityLevel.THREATENED)
        self.assertIn(assessment, awareness.threatened)

    def test_only_the_actually_threatened_base_is_reported(self):
        facts = world(
            own_structures=(
                townhall(1, MAP.own_start),
                townhall(2, Point2((40, 40))),
            ),
            enemy_units=(marine(50, Point2((12, 10))),),
        )

        awareness = BaseSecurityAssessor().update(facts)

        self.assertEqual(len(awareness.threatened), 1)
        self.assertEqual(awareness.threatened[0].base_id, "base:1")
        self.assertEqual(awareness.get("base:2").security, BaseSecurityLevel.SAFE)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.adapters.ares.depot_toggle import DepotToggle


class FakeDepot:
    def __init__(self, type_id: UnitTypeId, position: Point2) -> None:
        self.type_id = type_id
        self.position = position
        self.commands: list = []

    def distance_to(self, other) -> float:
        return self.position.distance_to(other.position)

    def __call__(self, ability: AbilityId) -> None:
        self.commands.append(ability)


class FakeEnemy:
    def __init__(self, position: Point2, *, is_flying: bool = False) -> None:
        self.position = position
        self.is_flying = is_flying


class FakeAi:
    def __init__(self, *, depots, enemy_units) -> None:
        self._depots = depots
        self.enemy_units = enemy_units

    def structures(self, unit_type: UnitTypeId):
        return [depot for depot in self._depots if depot.type_id == unit_type]


class DepotToggleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.behavior = DepotToggle(threat_radius=6.5)

    def test_lowers_a_raised_depot_with_no_enemy_nearby(self):
        depot = FakeDepot(UnitTypeId.SUPPLYDEPOT, Point2((10, 10)))
        ai = FakeAi(depots=[depot], enemy_units=[])

        did_action = self.behavior.execute(ai, {}, None)

        self.assertTrue(did_action)
        self.assertEqual(depot.commands, [AbilityId.MORPH_SUPPLYDEPOT_LOWER])

    def test_keeps_a_raised_depot_up_when_a_ground_enemy_is_close(self):
        depot = FakeDepot(UnitTypeId.SUPPLYDEPOT, Point2((10, 10)))
        enemy = FakeEnemy(Point2((12, 10)))
        ai = FakeAi(depots=[depot], enemy_units=[enemy])

        did_action = self.behavior.execute(ai, {}, None)

        self.assertFalse(did_action)
        self.assertEqual(depot.commands, [])

    def test_raises_a_lowered_depot_when_a_ground_enemy_approaches(self):
        depot = FakeDepot(UnitTypeId.SUPPLYDEPOTLOWERED, Point2((10, 10)))
        enemy = FakeEnemy(Point2((12, 10)))
        ai = FakeAi(depots=[depot], enemy_units=[enemy])

        did_action = self.behavior.execute(ai, {}, None)

        self.assertTrue(did_action)
        self.assertEqual(depot.commands, [AbilityId.MORPH_SUPPLYDEPOT_RAISE])

    def test_leaves_a_lowered_depot_alone_with_no_enemy_nearby(self):
        depot = FakeDepot(UnitTypeId.SUPPLYDEPOTLOWERED, Point2((10, 10)))
        ai = FakeAi(depots=[depot], enemy_units=[])

        did_action = self.behavior.execute(ai, {}, None)

        self.assertFalse(did_action)
        self.assertEqual(depot.commands, [])

    def test_a_distant_ground_enemy_does_not_prevent_lowering(self):
        depot = FakeDepot(UnitTypeId.SUPPLYDEPOT, Point2((10, 10)))
        far_enemy = FakeEnemy(Point2((40, 40)))
        ai = FakeAi(depots=[depot], enemy_units=[far_enemy])

        did_action = self.behavior.execute(ai, {}, None)

        self.assertTrue(did_action)
        self.assertEqual(depot.commands, [AbilityId.MORPH_SUPPLYDEPOT_LOWER])

    def test_a_flying_enemy_never_keeps_a_depot_raised(self):
        depot = FakeDepot(UnitTypeId.SUPPLYDEPOT, Point2((10, 10)))
        flying_enemy = FakeEnemy(Point2((11, 10)), is_flying=True)
        ai = FakeAi(depots=[depot], enemy_units=[flying_enemy])

        did_action = self.behavior.execute(ai, {}, None)

        self.assertTrue(did_action)
        self.assertEqual(depot.commands, [AbilityId.MORPH_SUPPLYDEPOT_LOWER])

    def test_no_depots_is_a_no_op(self):
        ai = FakeAi(depots=[], enemy_units=[])

        self.assertFalse(self.behavior.execute(ai, {}, None))


if __name__ == "__main__":
    unittest.main()

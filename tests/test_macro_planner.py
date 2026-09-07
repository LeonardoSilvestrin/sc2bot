from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention.models import (
    AttentionSnapshot,
    MapFacts,
    UnitSnapshot,
    WorldFacts,
)
from bot.awareness import AwarenessService
from bot.contracts.economy import EconomicActionKind
from bot.planners import MacroPlanner

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)


def townhall(tag: int = 1, *, is_ready: bool = True) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.COMMANDCENTER,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=False,
        is_structure=True,
        is_ready=is_ready,
    )


def worker(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.SCV,
        position=Point2((11, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=True,
        can_attack_air=False,
        can_attack_ground=True,
    )


def enemy_unit(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=Point2((90, 90)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
        visible_now=True,
    )


def economy_attention(
    *,
    time: float = 100.0,
    workers: int = 16,
    townhalls: int = 1,
    minerals: int = 500,
    vespene: int = 0,
    supply_used: float = 16.0,
    supply_cap: float = 30.0,
    visible_enemies: int = 0,
) -> AttentionSnapshot:
    world = WorldFacts(
        iteration=int(time),
        time=time,
        minerals=minerals,
        vespene=vespene,
        supply_used=supply_used,
        supply_cap=supply_cap,
        own_units=tuple(worker(tag) for tag in range(1, workers + 1)),
        enemy_units=tuple(enemy_unit(9000 + tag) for tag in range(visible_enemies)),
        map=MAP,
        own_structures=tuple(townhall(tag) for tag in range(1, townhalls + 1)),
    )
    return AttentionSnapshot(world)


class MacroPlannerTests(unittest.TestCase):
    def test_no_proposal_when_economy_is_balanced(self):
        attention = economy_attention(
            workers=16,
            townhalls=1,
            minerals=100,
            supply_used=16.0,
            supply_cap=30.0,
        )
        awareness = AwarenessService().update(attention)

        self.assertEqual(MacroPlanner().propose(attention, awareness), ())

    def test_no_worker_proposal_when_resources_are_insufficient(self):
        attention = economy_attention(
            workers=10,
            townhalls=1,
            minerals=10,
            supply_used=10.0,
            supply_cap=30.0,
        )
        awareness = AwarenessService().update(attention)

        self.assertEqual(MacroPlanner().propose(attention, awareness), ())

    def test_proposes_worker_when_below_ideal_and_affordable(self):
        attention = economy_attention(
            workers=10,
            townhalls=1,
            minerals=200,
            supply_used=10.0,
            supply_cap=30.0,
        )
        awareness = AwarenessService().update(attention)

        proposals = MacroPlanner().propose(attention, awareness)

        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.kind, EconomicActionKind.PRODUCE_WORKER)
        self.assertEqual(proposal.reason, "worker_count_below_ideal_for_current_bases")
        self.assertEqual(proposal.cost.minerals, 50)
        self.assertTrue(proposal.reason.strip())
        self.assertTrue(0 <= proposal.priority <= 100)

    def test_proposes_supply_when_near_supply_cap(self):
        attention = economy_attention(
            workers=16,
            townhalls=1,
            minerals=200,
            supply_used=26.0,
            supply_cap=30.0,
        )
        awareness = AwarenessService().update(attention)

        proposals = MacroPlanner().propose(attention, awareness)

        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.kind, EconomicActionKind.PRODUCE_SUPPLY)
        self.assertEqual(proposal.reason, "supply_capacity_near_limit")

    def test_no_supply_proposal_at_the_absolute_supply_cap(self):
        attention = economy_attention(
            workers=16,
            townhalls=1,
            minerals=200,
            supply_used=198.0,
            supply_cap=200.0,
        )
        awareness = AwarenessService().update(attention)

        proposals = MacroPlanner().propose(attention, awareness)

        self.assertEqual(
            [p.kind for p in proposals],
            [],
        )

    def test_proposes_expansion_when_saturated_and_safe(self):
        attention = economy_attention(
            workers=16,
            townhalls=1,
            minerals=500,
            supply_used=16.0,
            supply_cap=30.0,
        )
        awareness = AwarenessService().update(attention)

        proposals = MacroPlanner().propose(attention, awareness)

        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.kind, EconomicActionKind.EXPAND)
        self.assertEqual(proposal.reason, "worker_count_saturated_for_current_bases")
        self.assertEqual(proposal.cost.minerals, 400)

    def test_withholds_expansion_while_enemies_are_visible(self):
        attention = economy_attention(
            workers=16,
            townhalls=1,
            minerals=500,
            supply_used=16.0,
            supply_cap=30.0,
            visible_enemies=1,
        )
        awareness = AwarenessService().update(attention)

        self.assertEqual(MacroPlanner().propose(attention, awareness), ())

    def test_propose_is_deterministic_for_the_same_snapshot(self):
        attention = economy_attention(
            workers=10,
            townhalls=1,
            minerals=200,
            supply_used=26.0,
            supply_cap=30.0,
        )
        awareness = AwarenessService().update(attention)
        planner = MacroPlanner()

        first = planner.propose(attention, awareness)
        second = planner.propose(attention, awareness)

        self.assertEqual(first, second)
        self.assertEqual(
            [p.kind for p in first],
            [EconomicActionKind.PRODUCE_SUPPLY, EconomicActionKind.PRODUCE_WORKER],
        )


if __name__ == "__main__":
    unittest.main()

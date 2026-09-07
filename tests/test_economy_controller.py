from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention.models import AttentionSnapshot, MapFacts, UnitSnapshot, WorldFacts
from bot.contracts.economy import EconomicActionKind, EconomicProposal, ResourceCost
from bot.ego import EconomyController
from bot.planners import MacroPlannerConfig
from tests.fakes import FakeEconomyCommands, FakeLogger

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)


def townhall(tag: int = 1) -> UnitSnapshot:
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
        is_ready=True,
    )


def attention_at(
    *, time: float = 100.0, minerals: int = 500, vespene: int = 0
) -> AttentionSnapshot:
    world = WorldFacts(
        iteration=int(time),
        time=time,
        minerals=minerals,
        vespene=vespene,
        supply_used=16.0,
        supply_cap=30.0,
        own_units=(),
        enemy_units=(),
        map=MAP,
        own_structures=(townhall(),),
    )
    return AttentionSnapshot(world)


def worker_proposal(*, priority: int = 50, minerals: int = 50) -> EconomicProposal:
    return EconomicProposal(
        proposal_id="macro_planner:worker:100.0",
        planner="macro_planner",
        kind=EconomicActionKind.PRODUCE_WORKER,
        priority=priority,
        reason="worker_count_below_ideal_for_current_bases",
        cost=ResourceCost(minerals=minerals, supply=1.0),
        created_at=100.0,
    )


def supply_proposal(*, priority: int = 90, minerals: int = 100) -> EconomicProposal:
    return EconomicProposal(
        proposal_id="macro_planner:supply:100.0",
        planner="macro_planner",
        kind=EconomicActionKind.PRODUCE_SUPPLY,
        priority=priority,
        reason="supply_capacity_near_limit",
        cost=ResourceCost(minerals=minerals),
        created_at=100.0,
    )


def expand_proposal(*, priority: int = 60, minerals: int = 400) -> EconomicProposal:
    return EconomicProposal(
        proposal_id="macro_planner:expand:100.0",
        planner="macro_planner",
        kind=EconomicActionKind.EXPAND,
        priority=priority,
        reason="worker_count_saturated_for_current_bases",
        cost=ResourceCost(minerals=minerals),
        created_at=100.0,
    )


class EconomyControllerTests(unittest.TestCase):
    def test_admits_affordable_worker_proposal_and_dispatches_to_count(self):
        controller = EconomyController(
            logger=FakeLogger(), config=MacroPlannerConfig(max_workers=80)
        )
        commands = FakeEconomyCommands()

        controller.tick(
            attention=attention_at(minerals=500),
            proposals=(worker_proposal(),),
            commands=commands,
        )

        self.assertEqual(commands.commands, [("produce_worker", 80)])

    def test_admitted_proposal_logs_once_across_consecutive_ticks(self):
        logger = FakeLogger()
        controller = EconomyController(logger=logger, config=MacroPlannerConfig())
        commands = FakeEconomyCommands()

        controller.tick(
            attention=attention_at(minerals=500),
            proposals=(worker_proposal(),),
            commands=commands,
        )
        controller.tick(
            attention=attention_at(minerals=500),
            proposals=(worker_proposal(),),
            commands=commands,
        )

        admitted = [
            e for e in logger.events if e["name"] == "economy.proposal_admitted"
        ]
        self.assertEqual(len(admitted), 1)
        self.assertEqual(len(commands.commands), 2)

    def test_lower_priority_proposal_rejected_when_bank_is_reserved(self):
        logger = FakeLogger()
        controller = EconomyController(logger=logger, config=MacroPlannerConfig())
        commands = FakeEconomyCommands()

        controller.tick(
            attention=attention_at(minerals=120),
            proposals=(
                supply_proposal(priority=90, minerals=100),
                worker_proposal(priority=50, minerals=50),
            ),
            commands=commands,
        )

        self.assertEqual(
            [c[0] for c in commands.commands],
            ["produce_supply"],
        )
        rejection = next(
            e for e in logger.events if e["name"] == "economy.proposal_rejected"
        )
        self.assertEqual(rejection["data"]["reason"], "insufficient_reserved_resources")
        self.assertEqual(rejection["data"]["kind"], "PRODUCE_WORKER")

    def test_resolved_action_is_logged_once_kind_stops_being_proposed(self):
        logger = FakeLogger()
        controller = EconomyController(logger=logger, config=MacroPlannerConfig())
        commands = FakeEconomyCommands()

        controller.tick(
            attention=attention_at(minerals=500),
            proposals=(worker_proposal(),),
            commands=commands,
        )
        controller.tick(
            attention=attention_at(minerals=500),
            proposals=(),
            commands=commands,
        )

        resolved = [e for e in logger.events if e["name"] == "economy.action_resolved"]
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["data"]["kind"], "PRODUCE_WORKER")

    def test_expand_dispatches_ready_townhall_count_plus_one(self):
        controller = EconomyController(logger=FakeLogger(), config=MacroPlannerConfig())
        commands = FakeEconomyCommands()

        controller.tick(
            attention=attention_at(minerals=500),
            proposals=(expand_proposal(),),
            commands=commands,
        )

        self.assertEqual(commands.commands, [("expand", 2)])

    def test_supply_dispatches_own_start_as_base_location(self):
        controller = EconomyController(logger=FakeLogger(), config=MacroPlannerConfig())
        commands = FakeEconomyCommands()

        controller.tick(
            attention=attention_at(minerals=500),
            proposals=(supply_proposal(),),
            commands=commands,
        )

        self.assertEqual(commands.commands, [("produce_supply", MAP.own_start)])


if __name__ == "__main__":
    unittest.main()

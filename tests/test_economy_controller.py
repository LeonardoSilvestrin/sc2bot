from __future__ import annotations

import unittest

<<<<<<< HEAD
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
=======
from bot.contracts.economy import (
    EconomicActionKind,
    EconomicActionStatus,
    EconomicFeedback,
    EconomicFeedbackKind,
    EconomicProposal,
    ResourceBank,
    ResourceCost,
)
from bot.economy import EconomyController
from tests.fakes import FakeLogger


def proposal(
    proposal_id: str,
    *,
    key: str,
    priority: int = 50,
    minerals: int = 50,
    vespene: int = 0,
    supply: float = 0.0,
    kind: EconomicActionKind = EconomicActionKind.PRODUCE_WORKER,
    target: str | None = None,
    created_at: float = 1.0,
    dispatch_timeout: float = 5.0,
    confirmation_timeout: float = 30.0,
) -> EconomicProposal:
    return EconomicProposal(
        proposal_id=proposal_id,
        deduplication_key=key,
        planner="test_planner",
        kind=kind,
        priority=priority,
        target=target,
        reason="test_deficit",
        cost=ResourceCost(
            minerals=minerals,
            vespene=vespene,
            supply=supply,
        ),
        created_at=created_at,
        dispatch_timeout_seconds=dispatch_timeout,
        confirmation_timeout_seconds=confirmation_timeout,
    )


class ResourceBankTests(unittest.TestCase):
    def test_reserve_accounts_for_both_resources_and_supply(self):
        bank = ResourceBank(minerals=150, vespene=75, supply_available=4.0)

        remaining = bank.reserve(
            ResourceCost(minerals=100, vespene=50, supply=2.5)
        )

        self.assertEqual(
            remaining,
            ResourceBank(minerals=50, vespene=25, supply_available=1.5),
        )

    def test_hold_towards_never_makes_the_virtual_bank_negative(self):
        bank = ResourceBank(minerals=100, vespene=25, supply_available=1.0)

        remaining = bank.hold_towards(
            ResourceCost(minerals=400, vespene=100, supply=3.0)
        )

        self.assertEqual(
            remaining,
            ResourceBank(minerals=0, vespene=0, supply_available=0.0),
        )


class EconomyControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = FakeLogger()
        self.controller = EconomyController(logger=self.logger)

    def test_admits_by_priority_against_one_virtual_bank(self):
        lower = proposal("worker", key="worker:17", priority=50, minerals=50)
        higher = proposal(
            "supply",
            key="supply:2",
            priority=90,
            minerals=100,
            kind=EconomicActionKind.PRODUCE_SUPPLY,
        )

        result = self.controller.tick(
            now=1.0,
            bank=ResourceBank(100, 0, 10.0),
            proposals=(lower, higher),
        )

        self.assertEqual(
            [action.proposal.proposal_id for action in result.admitted_actions],
            ["supply"],
        )
        self.assertEqual(result.available_bank, ResourceBank(0, 0, 10.0))
        self.assertEqual(result.reserved_cost, ResourceCost(minerals=100))

    def test_tie_breaking_is_deterministic(self):
        later_id = proposal(
            "z-id", key="z-key", created_at=2.0, minerals=50
        )
        earlier_id = proposal(
            "a-id", key="a-key", created_at=1.0, minerals=50
        )

        result = self.controller.tick(
            now=2.0,
            bank=ResourceBank(50, 0, 10.0),
            proposals=(later_id, earlier_id),
        )

        self.assertEqual(
            [action.proposal.proposal_id for action in result.admitted_actions],
            ["a-id"],
        )

    def test_unaffordable_high_priority_proposal_holds_savings(self):
        expansion = proposal(
            "expand",
            key="base:2",
            priority=80,
            minerals=400,
            kind=EconomicActionKind.EXPAND,
        )
        worker = proposal("worker", key="worker:17", priority=50, minerals=50)

        result = self.controller.tick(
            now=1.0,
            bank=ResourceBank(300, 0, 10.0),
            proposals=(worker, expansion),
        )

        self.assertEqual(result.admitted_actions, ())
        self.assertEqual(result.available_bank.minerals, 0)
        self.assertEqual(result.reserved_cost.minerals, 300)
        deferred = [
            event
            for event in self.logger.events
            if event["name"] == "economic_proposal_deferred"
        ]
        self.assertEqual(deferred[0]["data"]["proposal_id"], "expand")

    def test_a_gas_shortage_does_not_hold_unneeded_minerals(self):
        gas_limited = proposal(
            "upgrade",
            key="upgrade:stim",
            priority=80,
            minerals=0,
            vespene=100,
            kind=EconomicActionKind.RESEARCH_UPGRADE,
            target="STIMPACK",
        )
        mineral_only = proposal(
            "worker", key="worker:17", priority=50, minerals=50
        )

        result = self.controller.tick(
            now=1.0,
            bank=ResourceBank(50, 0, 10.0),
            proposals=(gas_limited, mineral_only),
        )

        self.assertEqual(
            [action.proposal.proposal_id for action in result.admitted_actions],
            ["worker"],
        )

    def test_live_action_deduplicates_a_new_proposal_id_by_stable_key(self):
        first = proposal("worker-frame-1", key="worker:17")
        first_result = self.controller.tick(
            now=1.0,
            bank=ResourceBank(100, 0, 10.0),
            proposals=(first,),
        )
        second = proposal("worker-frame-2", key="worker:17", created_at=2.0)

        second_result = self.controller.tick(
            now=2.0,
            bank=ResourceBank(100, 0, 10.0),
            proposals=(second,),
        )

        self.assertEqual(len(first_result.admitted_actions), 1)
        self.assertEqual(second_result.admitted_actions, ())
        self.assertEqual(second_result.available_bank.minerals, 50)
        rejected = [
            event
            for event in self.logger.events
            if event["name"] == "economic_proposal_rejected"
        ]
        self.assertEqual(
            rejected[-1]["data"]["reason"],
            "matching_economic_action_already_live",
        )

    def test_only_highest_ranked_duplicate_is_considered_in_one_tick(self):
        lower = proposal("lower", key="worker:17", priority=40)
        higher = proposal("higher", key="worker:17", priority=80)

        result = self.controller.tick(
            now=1.0,
            bank=ResourceBank(100, 0, 10.0),
            proposals=(lower, higher),
        )

        self.assertEqual(
            [action.proposal.proposal_id for action in result.admitted_actions],
            ["higher"],
        )

    def test_dispatch_moves_in_flight_and_releases_bank_reservation(self):
        worker = proposal("worker", key="worker:17", minerals=50)
        admitted = self.controller.tick(
            now=1.0,
            bank=ResourceBank(100, 0, 10.0),
            proposals=(worker,),
        ).admitted_actions[0]
        supply = proposal(
            "supply",
            key="supply:2",
            minerals=100,
            kind=EconomicActionKind.PRODUCE_SUPPLY,
            created_at=2.0,
        )

        result = self.controller.tick(
            now=2.0,
            bank=ResourceBank(100, 0, 10.0),
            proposals=(supply,),
            feedback=(
                EconomicFeedback(
                    admitted.action_id,
                    EconomicFeedbackKind.DISPATCHED,
                    "command_accepted",
                ),
            ),
        )

        self.assertEqual(
            self.controller.snapshots()[0].status,
            EconomicActionStatus.IN_FLIGHT,
        )
        self.assertEqual(
            [action.proposal.proposal_id for action in result.admitted_actions],
            ["supply"],
        )

    def test_confirmation_is_terminal_and_allows_the_key_to_be_reused(self):
        worker = proposal("worker-17", key="worker:17")
        action = self.controller.tick(
            now=1.0,
            bank=ResourceBank(50, 0, 10.0),
            proposals=(worker,),
        ).admitted_actions[0]
        next_worker = proposal(
            "worker-18", key="worker:17", created_at=2.0
        )

        result = self.controller.tick(
            now=2.0,
            bank=ResourceBank(50, 0, 10.0),
            proposals=(next_worker,),
            feedback=(
                EconomicFeedback(
                    action.action_id,
                    EconomicFeedbackKind.CONFIRMED,
                    "pending_count_increased",
                ),
            ),
        )

        snapshots = self.controller.snapshots()
        self.assertEqual(snapshots[0].status, EconomicActionStatus.COMPLETED)
        self.assertEqual(len(result.admitted_actions), 1)
        self.assertNotEqual(result.admitted_actions[0].action_id, action.action_id)

    def test_dispatch_and_confirmation_can_arrive_in_the_same_tick(self):
        worker = proposal("worker-17", key="worker:17")
        action = self.controller.tick(
            now=1.0,
            bank=ResourceBank(50, 0, 10.0),
            proposals=(worker,),
        ).admitted_actions[0]

        self.controller.tick(
            now=2.0,
            bank=ResourceBank(0, 0, 9.0),
            feedback=(
                EconomicFeedback(
                    action.action_id,
                    EconomicFeedbackKind.DISPATCHED,
                    "train_command_accepted",
                ),
                EconomicFeedback(
                    action.action_id,
                    EconomicFeedbackKind.CONFIRMED,
                    "worker_pending",
                ),
            ),
        )

        snapshot = self.controller.snapshots()[0]
        self.assertEqual(snapshot.status, EconomicActionStatus.COMPLETED)
        self.assertEqual(snapshot.reason, "worker_pending")

    def test_failure_releases_dedupe_for_a_later_retry(self):
        worker = proposal("worker", key="worker:17")
        action = self.controller.tick(
            now=1.0,
            bank=ResourceBank(50, 0, 10.0),
            proposals=(worker,),
        ).admitted_actions[0]

        self.controller.tick(
            now=2.0,
            bank=ResourceBank(50, 0, 10.0),
            feedback=(
                EconomicFeedback(
                    action.action_id,
                    EconomicFeedbackKind.FAILED,
                    "placement_failed",
                ),
            ),
        )
        retry = self.controller.tick(
            now=3.0,
            bank=ResourceBank(50, 0, 10.0),
            proposals=(worker,),
        )

        self.assertEqual(
            self.controller.snapshots()[0].status,
            EconomicActionStatus.FAILED,
        )
        self.assertEqual(len(retry.admitted_actions), 1)

    def test_pending_action_times_out_and_does_not_readmit_same_tick(self):
        worker = proposal(
            "worker", key="worker:17", dispatch_timeout=2.0
        )
        self.controller.tick(
            now=1.0,
            bank=ResourceBank(50, 0, 10.0),
            proposals=(worker,),
        )

        at_timeout = self.controller.tick(
            now=3.0,
            bank=ResourceBank(50, 0, 10.0),
            proposals=(worker,),
        )
        retry = self.controller.tick(
            now=3.1,
            bank=ResourceBank(50, 0, 10.0),
            proposals=(worker,),
        )

        self.assertEqual(at_timeout.admitted_actions, ())
        self.assertEqual(
            self.controller.snapshots()[0].status,
            EconomicActionStatus.TIMED_OUT,
        )
        self.assertEqual(self.controller.snapshots()[0].reason, "dispatch_timeout")
        self.assertEqual(len(retry.admitted_actions), 1)

    def test_in_flight_action_uses_confirmation_timeout(self):
        upgrade = proposal(
            "stim",
            key="upgrade:stim",
            minerals=100,
            vespene=100,
            kind=EconomicActionKind.RESEARCH_UPGRADE,
            target="STIMPACK",
            confirmation_timeout=4.0,
        )
        action = self.controller.tick(
            now=1.0,
            bank=ResourceBank(100, 100, 10.0),
            proposals=(upgrade,),
        ).admitted_actions[0]
        self.controller.tick(
            now=2.0,
            bank=ResourceBank(0, 0, 10.0),
            feedback=(
                EconomicFeedback(
                    action.action_id,
                    EconomicFeedbackKind.DISPATCHED,
                    "research_started",
                ),
            ),
        )

        self.controller.tick(
            now=6.0,
            bank=ResourceBank(0, 0, 10.0),
        )

        snapshot = self.controller.snapshots()[0]
        self.assertEqual(snapshot.status, EconomicActionStatus.TIMED_OUT)
        self.assertEqual(snapshot.reason, "confirmation_timeout")

    def test_unknown_feedback_is_logged_without_crashing(self):
        result = self.controller.tick(
            now=1.0,
            bank=ResourceBank(0, 0, 0.0),
            feedback=(
                EconomicFeedback(
                    "missing",
                    EconomicFeedbackKind.FAILED,
                    "adapter_rejected",
                ),
            ),
        )

        self.assertEqual(result.admitted_actions, ())
        event = self.logger.events[-1]
        self.assertEqual(event["name"], "economic_feedback_rejected")
        self.assertEqual(event["component"], "economy.controller")
        self.assertEqual(event["data"]["reason"], "unknown_economic_action")

    def test_default_dedupe_key_is_stable_across_frame_timestamps(self):
        first = EconomicProposal(
            proposal_id="frame-1",
            planner="macro",
            kind=EconomicActionKind.PRODUCE_UNIT,
            priority=50,
            reason="composition_deficit",
            cost=ResourceCost(50, 0, 1.0),
            created_at=1.0,
            target="MARINE",
        )
        second = EconomicProposal(
            proposal_id="frame-2",
            planner="macro",
            kind=EconomicActionKind.PRODUCE_UNIT,
            priority=50,
            reason="composition_deficit",
            cost=ResourceCost(50, 0, 1.0),
            created_at=2.0,
            target="MARINE",
        )

        self.assertEqual(first.deduplication_key, second.deduplication_key)
        self.assertEqual(
            first.deduplication_key,
            "macro:produce_unit:MARINE",
        )

    def test_rejects_time_travel(self):
        self.controller.tick(now=2.0, bank=ResourceBank(0, 0, 0.0))

        with self.assertRaises(ValueError):
            self.controller.tick(now=1.0, bank=ResourceBank(0, 0, 0.0))
>>>>>>> agents/codex


if __name__ == "__main__":
    unittest.main()

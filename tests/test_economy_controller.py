from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.position import Point2

from bot.engine.economy import EconomyController
from bot.engine.economy.models import (
    EconomicActionKind,
    EconomicActionStatus,
    EconomicFeedback,
    EconomicFeedbackKind,
    EconomicProposal,
    ResourceBank,
    ResourceCost,
)
from bot.world.attention import (
    AttentionSnapshot,
    CountFacts,
    EconomyFacts,
    MapFacts,
    WorldFacts,
)
from tests.fakes import FakeEconomyCommands, FakeLogger


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

    def test_protected_resources_are_out_of_reach_of_low_priority_spending(self):
        # 300 in the bank, 250 spoken for by a timing the build runner owns:
        # a 50 mineral Marine is fine, a 150 mineral Barracks is not, however
        # affordable it looks against the raw bank.
        marine = proposal(
            "marine",
            key="army:marine",
            priority=70,
            minerals=50,
            kind=EconomicActionKind.PRODUCE_UNIT,
            target="MARINE",
        )
        barracks = proposal(
            "barracks",
            key="production:barracks",
            priority=64,
            minerals=150,
            kind=EconomicActionKind.BUILD_PRODUCTION,
            target="BARRACKS",
        )

        result = self.controller.tick(
            now=1.0,
            bank=ResourceBank(300, 0, 10.0),
            proposals=(marine, barracks),
            protected=ResourceCost(minerals=250),
        )

        self.assertEqual(
            [action.proposal.proposal_id for action in result.admitted_actions],
            ["marine"],
        )
        self.assertEqual(result.protected_cost, ResourceCost(minerals=250))
        self.assertEqual(result.reserved_cost, ResourceCost(minerals=50))
        deferred = [
            event
            for event in self.logger.events
            if event["name"] == "economic_proposal_deferred"
        ]
        self.assertEqual(deferred[-1]["data"]["proposal_id"], "barracks")
        self.assertEqual(
            deferred[-1]["data"]["reason"],
            "protected_commitment_holds_resources",
        )

    def test_protection_is_capped_by_what_the_bank_actually_holds(self):
        worker = proposal("worker", key="worker:17", minerals=50)

        result = self.controller.tick(
            now=1.0,
            bank=ResourceBank(30, 0, 10.0),
            proposals=(worker,),
            protected=ResourceCost(minerals=400),
        )

        self.assertEqual(result.admitted_actions, ())
        self.assertEqual(result.protected_cost, ResourceCost(minerals=30))

    def test_only_the_next_purchase_is_saved_for(self):
        # Two proposals we cannot buy yet, both gated on gas we do not have.
        # Saving minerals for each of them in turn would bank the whole pile
        # against purchases that are nowhere near possible and leave nothing
        # for the Marine, which is exactly how a bot ends up rich and idle.
        tank = proposal(
            "tank",
            key="army:tank",
            priority=72,
            minerals=150,
            vespene=125,
            kind=EconomicActionKind.PRODUCE_UNIT,
            target="SIEGETANK",
        )
        medivac = proposal(
            "medivac",
            key="army:medivac",
            priority=71,
            minerals=100,
            vespene=100,
            kind=EconomicActionKind.PRODUCE_UNIT,
            target="MEDIVAC",
        )
        marine = proposal(
            "marine",
            key="army:marine",
            priority=70,
            minerals=50,
            kind=EconomicActionKind.PRODUCE_UNIT,
            target="MARINE",
        )

        result = self.controller.tick(
            now=1.0,
            bank=ResourceBank(200, 0, 10.0),
            proposals=(tank, medivac, marine),
        )

        self.assertEqual(
            [action.proposal.proposal_id for action in result.admitted_actions],
            ["marine"],
        )
        # 150 saved for the Tank, 50 spent on the Marine, nothing left over.
        self.assertEqual(result.reserved_cost, ResourceCost(minerals=200))

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
        self.assertEqual(event["component"], "engine.economy.controller")
        self.assertEqual(event["data"]["reason"], "unknown_economic_action")

    def test_repeated_proposal_outcomes_are_logged_only_on_transition(self):
        blocked = proposal("stable-worker", key="worker:17", minerals=50)

        for now in (1.0, 2.0, 3.0):
            self.controller.tick(
                now=now,
                bank=ResourceBank(0, 0, 10.0),
                proposals=(blocked,),
            )

        deferred = [
            event
            for event in self.logger.events
            if event["name"] == "economic_proposal_deferred"
        ]
        self.assertEqual(len(deferred), 1)

    def test_live_proposal_rejection_is_logged_again_only_when_status_changes(self):
        worker = proposal("stable-worker", key="worker:17")
        action = self.controller.tick(
            now=1.0,
            bank=ResourceBank(50, 0, 10.0),
            proposals=(worker,),
        ).admitted_actions[0]

        for now in (2.0, 3.0):
            self.controller.tick(
                now=now,
                bank=ResourceBank(50, 0, 10.0),
                proposals=(worker,),
            )
        self.controller.tick(
            now=4.0,
            bank=ResourceBank(50, 0, 10.0),
            proposals=(worker,),
            feedback=(
                EconomicFeedback(
                    action.action_id,
                    EconomicFeedbackKind.DISPATCHED,
                    "command_accepted",
                ),
            ),
        )

        rejected = [
            event
            for event in self.logger.events
            if event["name"] == "economic_proposal_rejected"
        ]
        self.assertEqual(len(rejected), 2)
        self.assertEqual(
            [event["data"]["status"] for event in rejected],
            ["PENDING", "IN_FLIGHT"],
        )

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


def economy_attention(
    *,
    time: float,
    minerals: int = 500,
    workers: int = 12,
    protected_minerals: int = 0,
) -> AttentionSnapshot:
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(time),
            time=time,
            minerals=minerals,
            vespene=0,
            supply_used=12.0,
            supply_cap=23.0,
            own_units=(),
            enemy_units=(),
            map=MapFacts(
                center=Point2((50, 50)),
                own_start=Point2((10, 10)),
                enemy_starts=(Point2((90, 90)),),
            ),
            economy=EconomyFacts(
                workers=CountFacts(existing=workers, ready=workers),
                protected_minerals=protected_minerals,
            ),
        )
    )


class EconomyControllerStepTests(unittest.TestCase):
    """`step` is one frame of the economic track: confirm, admit, dispatch."""

    def setUp(self) -> None:
        self.controller = EconomyController(logger=FakeLogger())
        self.commands = FakeEconomyCommands()

    def test_a_live_action_is_dispatched_again_every_frame(self):
        worker = proposal("worker", key="worker:13")

        for now in (1.0, 2.0):
            self.controller.step(
                attention=economy_attention(time=now),
                proposals=(worker,),
                commands=self.commands,
            )

        self.assertEqual(len(self.commands.commands), 2)
        # The port's report from frame one is applied on frame two.
        self.assertEqual(
            self.controller.snapshots()[0].status, EconomicActionStatus.IN_FLIGHT
        )

    def test_attention_confirms_an_action_and_ends_its_dispatch(self):
        worker = replace(proposal("worker", key="worker:13"), target_count=13)

        self.controller.step(
            attention=economy_attention(time=1.0, workers=12),
            proposals=(worker,),
            commands=self.commands,
        )
        self.controller.step(
            attention=economy_attention(time=2.0, workers=13),
            proposals=(),
            commands=self.commands,
        )

        self.assertEqual(
            self.controller.snapshots()[0].status, EconomicActionStatus.COMPLETED
        )
        self.assertEqual(len(self.commands.commands), 1)

    def test_the_opening_protection_is_read_from_attention(self):
        barracks = proposal(
            "barracks",
            key="production:barracks",
            minerals=150,
            kind=EconomicActionKind.BUILD_PRODUCTION,
            target="BARRACKS",
        )

        result = self.controller.step(
            attention=economy_attention(
                time=1.0, minerals=200, protected_minerals=100
            ),
            proposals=(barracks,),
            commands=self.commands,
        )

        self.assertEqual(result.admitted_actions, ())
        self.assertEqual(result.protected_cost, ResourceCost(minerals=100))
        self.assertEqual(self.commands.commands, [])


if __name__ == "__main__":
    unittest.main()

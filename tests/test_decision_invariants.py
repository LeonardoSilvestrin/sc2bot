"""Relational invariants of the decision pipeline.

Each test states a relation any replacement model must keep, whatever its
numbers: the Mission Policy's monotonicity, what a control objective can
contribute, that rejected work never reaches the engine, exclusive and
conserved unit leases, terminal missions staying terminal, arbitration that
does not depend on input order, and logs that carry the evaluation that
decided. Randomized checks use fixed seeds, so a failure always reproduces.
"""

from __future__ import annotations

import itertools
import json
import random
import unittest
from dataclasses import replace
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app.mission_ranking import MissionRanker
from bot.app.run_identity import fingerprint
from bot.behavior.contracts import UNRANKED_PRIORITY, MissionCandidate
from bot.engine.missions.allocator import UnitAllocator
from bot.engine.missions.controller import (
    MissionController,
    admission_key,
    arbitration_key,
)
from bot.engine.missions.execution import (
    MissionExecutor,
    MissionOutcome,
    MissionResult,
)
from bot.engine.missions.models import (
    Mission,
    MissionKind,
    MissionMode,
    MissionProposal,
    MissionSnapshot,
    MissionStatus,
    UnitRequirement,
)
from bot.strategy.context import StrategicContext
from bot.strategy.intent import StrategicActivity, StrategicIntent
from bot.strategy.mission_policy import (
    MINIMUM_CONTROL_ALIGNMENT,
    ControlMatch,
    ControlNeed,
    MissionEvaluation,
    MissionSignals,
    evaluate_mission,
)
from bot.strategy.spatial.model import (
    ControlObjective,
    ControlTargetKind,
    SpatialStrategySnapshot,
)
from bot.world.attention import AttentionSnapshot, MapFacts, UnitSnapshot, WorldFacts
from bot.world.awareness import AwarenessSnapshot, RelativeStrength, ThreatAssessment
from bot.world.awareness.enemy import EnemyAwareness
from tests.fakes import FakeCommands, FakeLogger

SAMPLES = 400
ACTIVITIES = tuple(StrategicActivity)
MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)


def marine(tag: int) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.MARINE,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=True,
        can_attack_ground=True,
        supply_cost=1.0,
    )


def proposal(
    key: str,
    *,
    priority: int = 50,
    planner: str = "raids",
    proposal_id: str | None = None,
    desired: int = 1,
    minimum: int = 1,
    can_preempt: bool = False,
    mode: MissionMode = MissionMode.FINITE,
    kind: MissionKind = MissionKind.HARASS,
    commitment_seconds: float = 5.0,
    cooldown_seconds: float = 65.0,
    created_at: float = 0.0,
) -> MissionProposal:
    return MissionProposal(
        proposal_id=proposal_id or f"{key}#1",
        deduplication_key=key,
        planner=planner,
        kind=kind,
        priority=priority,
        target_key=key,
        target=MAP.center,
        reason="test",
        requirement=UnitRequirement.combat(
            unit_types=frozenset({UnitTypeId.MARINE}),
            desired=desired,
            minimum=minimum,
        ),
        created_at=created_at,
        can_preempt=can_preempt,
        commitment_seconds=commitment_seconds,
        cooldown_seconds=cooldown_seconds,
        mode=mode,
    )


def candidate(
    key: str, signals: MissionSignals, *, sequence: int = 1, **fields: Any
) -> MissionCandidate:
    draft = proposal(
        key, priority=UNRANKED_PRIORITY, proposal_id=f"{key}#{sequence}", **fields
    )
    return MissionCandidate(draft=draft, signals=signals)


def standing_candidate(sequence: int, now: float) -> MissionCandidate:
    return candidate(
        "standing:main",
        MissionSignals.fallback("owns idle units"),
        sequence=sequence,
        planner="standing",
        mode=MissionMode.STANDING,
        kind=MissionKind.HOLD_RALLY,
        desired=2,
        minimum=0,
        created_at=now,
    )


class HoldExecutor(MissionExecutor):
    async def step(self, context):
        return MissionResult(MissionOutcome.ACTIVE, "holding")


class CompleteExecutor(MissionExecutor):
    async def step(self, context):
        return MissionResult(MissionOutcome.COMPLETED, "done")


def build_executor(mission: Mission, now: float) -> MissionExecutor:
    if mission.proposal.deduplication_key.startswith("done:"):
        return CompleteExecutor()
    return HoldExecutor()


EXECUTORS = {kind: build_executor for kind in MissionKind}


async def run_tick(
    controller: MissionController,
    now: float,
    units: tuple[UnitSnapshot, ...],
    proposals: tuple[MissionProposal, ...],
    declared: frozenset[str] = frozenset(),
) -> None:
    attention = AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=float(len(units)),
            supply_cap=200.0,
            own_units=units,
            enemy_units=(),
            map=MAP,
        )
    )
    awareness = AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=now,
    )
    await controller.tick(
        attention=attention,
        awareness=awareness,
        proposals=proposals,
        commands=FakeCommands(),
        declared_planners=declared,
    )


def random_intent(rng: random.Random) -> StrategicIntent:
    return StrategicIntent(
        defense=rng.random(),
        map_control=rng.random(),
        harass=rng.random(),
        information=rng.random(),
        risk_tolerance=rng.random(),
    )


def random_signals(rng: random.Random) -> MissionSignals:
    control = (
        ControlMatch("objective", rng.uniform(MINIMUM_CONTROL_ALIGNMENT, 1.0))
        if rng.random() < 0.5
        else None
    )
    return MissionSignals(
        activity=rng.choice(ACTIVITIES),
        opportunity=rng.random(),
        urgency=rng.random(),
        risk=rng.random(),
        information_gain=rng.random(),
        control=control,
    )


def random_need(rng: random.Random) -> ControlNeed | None:
    if rng.random() < 0.2:
        return None
    return ControlNeed(importance=rng.random(), gap=rng.random())


def ordered(rng: random.Random) -> tuple[float, float]:
    low, high = sorted((rng.random(), rng.random()))
    return low, high


def region(**values: float) -> ControlObjective:
    fields: dict[str, float] = {
        "desired_control": 0.9,
        "desired_visibility": 0.6,
        "importance": 0.8,
        "current_control": 0.2,
        "current_visibility": 0.5,
    }
    fields.update(values)
    return ControlObjective(
        objective_id="region:1",
        kind=ControlTargetKind.REGION,
        target_key="region:1",
        position=Point2((40, 40)),
        activity=StrategicActivity.MAP_CONTROL,
        reason="contested_region",
        **fields,
    )


class MissionPolicyRelationTests(unittest.TestCase):
    def assert_not_better(
        self, worse: MissionEvaluation, better: MissionEvaluation
    ) -> None:
        self.assertLessEqual(worse.raw_utility, better.raw_utility)
        self.assertLessEqual(worse.utility, better.utility)
        if worse.viable:
            self.assertTrue(better.viable)
            assert worse.priority is not None and better.priority is not None
            self.assertLessEqual(worse.priority, better.priority)

    def test_more_risk_never_raises_utility_viability_or_rank(self):
        rng = random.Random(5101)
        for _ in range(SAMPLES):
            signals, intent, need = random_signals(rng), random_intent(rng), random_need(rng)
            low, high = ordered(rng)
            self.assert_not_better(
                evaluate_mission(replace(signals, risk=high), intent, need=need),
                evaluate_mission(replace(signals, risk=low), intent, need=need),
            )

    def test_more_urgency_never_lowers_utility_viability_or_rank(self):
        rng = random.Random(5102)
        for _ in range(SAMPLES):
            signals, intent, need = random_signals(rng), random_intent(rng), random_need(rng)
            low, high = ordered(rng)
            self.assert_not_better(
                evaluate_mission(replace(signals, urgency=low), intent, need=need),
                evaluate_mission(replace(signals, urgency=high), intent, need=need),
            )

    def test_more_strategic_desirability_never_lowers_utility_or_rank(self):
        rng = random.Random(5103)
        for _ in range(SAMPLES):
            signals, intent, need = random_signals(rng), random_intent(rng), random_need(rng)
            assert signals.activity is not None
            field = signals.activity.name.lower()
            low, high = ordered(rng)
            self.assert_not_better(
                evaluate_mission(signals, replace(intent, **{field: low}), need=need),
                evaluate_mission(signals, replace(intent, **{field: high}), need=need),
            )

    def test_work_serving_no_objective_gets_no_control_value(self):
        rng = random.Random(5104)
        for _ in range(SAMPLES):
            evaluation = evaluate_mission(
                replace(random_signals(rng), control=None),
                random_intent(rng),
                need=ControlNeed(importance=rng.random(), gap=rng.random()),
            )
            self.assertEqual(evaluation.control_contribution, 0.0)
            self.assertIsNone(evaluation.control_need)

    def test_an_alignment_below_the_minimum_is_no_match_at_all(self):
        for alignment in (0.0, 0.25, MINIMUM_CONTROL_ALIGNMENT - 1e-9):
            self.assertIsNone(ControlMatch.from_alignment("region:1", alignment))
            with self.assertRaises(ValueError):
                ControlMatch("region:1", alignment)

    def test_an_objective_the_context_no_longer_holds_contributes_nothing(self):
        context = StrategicContext(
            intent=StrategicContext.neutral().intent,
            spatial=SpatialStrategySnapshot(objectives=(region(),)),
            revision=1,
        )
        signals = MissionSignals(
            activity=StrategicActivity.MAP_CONTROL,
            opportunity=0.5,
            control=ControlMatch("region:gone", 1.0),
        )

        evaluation = evaluate_mission(
            signals, context.intent, need=context.need_for("region:gone")
        )

        self.assertEqual(evaluation.control_contribution, 0.0)
        self.assertIsNone(evaluation.control_need)

    def test_less_current_control_never_shrinks_the_gap_or_the_control_value(self):
        rng = random.Random(5105)
        for _ in range(SAMPLES):
            base = region(
                desired_control=rng.random(),
                desired_visibility=rng.random(),
                importance=rng.random(),
                current_visibility=rng.random(),
            )
            low, high = ordered(rng)
            weaker = replace(base, current_control=low)
            stronger = replace(base, current_control=high)
            self.assertGreaterEqual(weaker.control_gap, stronger.control_gap)
            self.assertGreaterEqual(weaker.gap, stronger.gap)
            less_seen = replace(base, current_visibility=low)
            more_seen = replace(base, current_visibility=high)
            self.assertGreaterEqual(less_seen.gap, more_seen.gap)

            signals = MissionSignals(
                activity=rng.choice(ACTIVITIES),
                opportunity=rng.random(),
                control=ControlMatch(
                    base.objective_id, rng.uniform(MINIMUM_CONTROL_ALIGNMENT, 1.0)
                ),
            )
            intent = random_intent(rng)
            self.assertGreaterEqual(
                evaluate_mission(signals, intent, need=weaker.need).control_contribution,
                evaluate_mission(signals, intent, need=stronger.need).control_contribution,
            )


class RejectedWorkTests(unittest.IsolatedAsyncioTestCase):
    """A rejected candidate has no rank, so it can neither outrank nor preempt
    the fallback owner. The same contest with viable work shows the scene
    does allow preemption: the rejection is what protects Standing."""

    async def contest(self, raid: MissionSignals):
        logger = FakeLogger()
        ranker = MissionRanker(logger=logger)
        controller = MissionController(logger=logger, executor_factories=EXECUTORS)
        units = (marine(1), marine(2))
        await run_tick(
            controller,
            0.0,
            units,
            ranker.rank((standing_candidate(1, 0.0),)),
            frozenset({"standing"}),
        )
        proposals = ranker.rank(
            (
                candidate("raid:a", raid, can_preempt=True, created_at=10.0),
                standing_candidate(2, 10.0),
            )
        )
        await run_tick(
            controller, 10.0, units, proposals, frozenset({"standing", "raids"})
        )
        missions = {item.deduplication_key: item for item in controller.snapshots()}
        return ranker, missions, logger, proposals

    async def test_rejected_work_never_takes_a_unit_from_standing(self):
        hopeless = MissionSignals(
            activity=StrategicActivity.HARASS, risk=1.0, reason="certain_losses"
        )

        ranker, missions, logger, proposals = await self.contest(hopeless)

        evaluation = ranker.last_evaluations["raid:a"]
        self.assertFalse(evaluation.viable)
        self.assertIsNone(evaluation.priority)
        self.assertEqual([item.deduplication_key for item in proposals], ["standing:main"])
        self.assertEqual(set(missions), {"standing:main"})
        self.assertEqual(missions["standing:main"].assigned_unit_tags, (1, 2))
        self.assertFalse(
            any(
                event["data"].get("deduplication_key") == "raid:a"
                for event in logger.events
                if event["component"] == "engine.missions.controller"
            )
        )

    async def test_the_same_contest_is_won_by_viable_work(self):
        promising = MissionSignals(
            activity=StrategicActivity.HARASS,
            opportunity=1.0,
            urgency=0.6,
            reason="worth_it",
        )

        ranker, missions, _, _ = await self.contest(promising)

        self.assertTrue(ranker.last_evaluations["raid:a"].viable)
        self.assertEqual(missions["raid:a"].assigned_unit_tags, (1,))
        self.assertEqual(missions["standing:main"].assigned_unit_tags, (2,))


class UnitLeaseRelationTests(unittest.TestCase):
    def test_leases_stay_exclusive_and_change_hands_only_by_rule(self):
        rng = random.Random(5106)
        types = (UnitTypeId.MARINE, UnitTypeId.MARAUDER, UnitTypeId.HELLION)
        roster = tuple(
            UnitSnapshot(
                tag=tag,
                unit_type=rng.choice(types),
                position=Point2((rng.uniform(0, 100), rng.uniform(0, 100))),
                health_percentage=rng.choice((0.4, 0.8, 1.0)),
                is_flying=False,
                is_worker=False,
                can_attack_air=True,
                can_attack_ground=True,
                supply_cost=rng.choice((1.0, 2.0)),
            )
            for tag in range(1, 13)
        )
        priorities = {f"m{index}": rng.choice((20, 30, 45, 60, 75, 90)) for index in range(5)}
        allocator = UnitAllocator(preemption_margin=10)
        units = roster
        allocator.sync(units)
        now = 0.0
        transfers_seen = 0

        for _ in range(400):
            now += rng.uniform(0.2, 2.0)
            if rng.random() < 0.1:
                units = tuple(unit for unit in roster if rng.random() < 0.85)
                allocator.sync(units)
            mission_id = rng.choice(sorted(priorities))
            priority = priorities[mission_id]
            wanted = frozenset(rng.sample(types, rng.randint(1, len(types))))
            desired = rng.randint(1, 5)
            can_preempt = rng.random() < 0.6
            requirement = UnitRequirement.combat(
                unit_types=wanted,
                desired=desired,
                minimum=rng.randint(0, desired),
                minimum_health=rng.choice((0.0, 0.7)),
                type_desirability=tuple(
                    (unit_type, rng.choice((0.0, 0.5, 1.0)))
                    for unit_type in sorted(wanted, key=lambda item: item.name)
                    if rng.random() < 0.5
                ),
                supply_budget=rng.choice((None, 2.0, 5.0)),
            )
            before = {unit.tag: allocator.owner_of(unit.tag) for unit in units}

            result = allocator.allocate(
                mission_id=mission_id,
                priority=priority,
                requirement=requirement,
                objective=Point2((rng.uniform(0, 100), rng.uniform(0, 100))),
                now=now,
                can_preempt=can_preempt,
                commitment_seconds=rng.choice((0.0, 1.0, 5.0)),
            )
            # As MissionController does: a released lease is dropped at once.
            allocator.release_units(mission_id, result.released_tags)
            after = {unit.tag: allocator.owner_of(unit.tag) for unit in units}

            held = {item: set(allocator.assigned_tags(item)) for item in priorities}
            for first, second in itertools.combinations(held, 2):
                self.assertFalse(held[first] & held[second])
            self.assertEqual(
                set().union(*held.values()),
                {tag for tag, owner in after.items() if owner is not None},
            )
            self.assertEqual(allocator.assigned_tags(mission_id), result.assigned_tags)

            transferred = {item.unit_tag: item for item in result.transfers}
            released = set(result.released_tags)
            self.assertFalse(released & set(result.assigned_tags))
            if transferred:
                self.assertTrue(can_preempt)
            for tag, previous in before.items():
                current = after[tag]
                if current == previous or (current == mission_id and previous is None):
                    continue
                if current == mission_id:
                    self.assertIn(tag, transferred)
                    self.assertEqual(transferred[tag].from_mission_id, previous)
                    self.assertEqual(transferred[tag].to_mission_id, mission_id)
                    assert previous is not None
                    self.assertGreaterEqual(
                        priority, priorities[previous] + allocator.preemption_margin
                    )
                else:
                    self.assertEqual((previous, current), (mission_id, None))
                    self.assertIn(tag, released)
            for tag in transferred:
                self.assertNotIn(before[tag], (None, mission_id))
            acquired = sum(
                1 for tag in before if before[tag] is None and after[tag] == mission_id
            )
            self.assertEqual(
                sum(owner is not None for owner in after.values()),
                sum(owner is not None for owner in before.values())
                + acquired
                - len(released),
            )
            transfers_seen += len(transferred)

        self.assertGreater(transfers_seen, 0, "the run never exercised preemption")


class TerminalMissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_terminal_mission_never_changes_again(self):
        logger = FakeLogger()
        controller = MissionController(logger=logger, executor_factories=EXECUTORS)
        units = (marine(1), marine(2), marine(3))
        terminal: dict[str, MissionSnapshot] = {}

        async def tick(now, proposals, declared=frozenset()):
            await run_tick(controller, now, units, tuple(proposals), declared)
            for snapshot in controller.snapshots():
                held = terminal.get(snapshot.mission_id)
                if held is not None:
                    self.assertEqual(snapshot, held)
                elif snapshot.status.terminal:
                    terminal[snapshot.mission_id] = snapshot
                    self.assertEqual(snapshot.assigned_unit_tags, ())
                    self.assertEqual(
                        controller.allocator.assigned_tags(snapshot.mission_id), ()
                    )

        standing = {
            "planner": "standing",
            "mode": MissionMode.STANDING,
            "kind": MissionKind.HOLD_RALLY,
            "priority": 20,
            "desired": 3,
            "minimum": 0,
            "cooldown_seconds": 0.0,
        }
        low_raid = proposal("raid:low", priority=40, commitment_seconds=1.0)
        # done:a completes at once; raid:low and standing hold units.
        await tick(
            0.0,
            (
                proposal("done:a", cooldown_seconds=5.0),
                low_raid,
                proposal("standing:main", **standing),
            ),
            frozenset({"standing"}),
        )
        # done:a is cooling down; raid:high preempts raid:low, which fails.
        await tick(
            2.0,
            (
                proposal("done:a", proposal_id="done:a#2", cooldown_seconds=5.0),
                proposal("raid:high", priority=90, desired=3, can_preempt=True),
                proposal("standing:main", proposal_id="standing:main#2", **standing),
            ),
            frozenset({"standing"}),
        )
        # The standing planner declares nothing: its mission is cancelled.
        await tick(4.0, (), frozenset({"standing"}))
        # Every key is proposed again; only new missions may result.
        await tick(
            8.0,
            (
                proposal("done:a", proposal_id="done:a#3", cooldown_seconds=5.0),
                proposal("standing:main", proposal_id="standing:main#3", **standing),
                proposal("raid:low", proposal_id="raid:low#2", priority=40),
            ),
            frozenset({"standing"}),
        )
        await tick(9.0, (low_raid,))

        self.assertEqual(
            {snapshot.status for snapshot in terminal.values()},
            {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED},
        )
        by_key: dict[str, set[str]] = {}
        for snapshot in controller.snapshots():
            by_key.setdefault(snapshot.deduplication_key, set()).add(snapshot.mission_id)
        self.assertEqual(len(by_key["done:a"]), 2)
        self.assertEqual(len(by_key["standing:main"]), 2)
        self.assertEqual(len(by_key["raid:low"]), 1)

        ended: set[str] = set()
        endings = {"mission_completed", "mission_failed", "mission_cancelled"}
        for event in logger.events:
            mission_id = event["data"].get("mission_id")
            if mission_id is None:
                continue
            self.assertNotIn(mission_id, ended, f"{event['name']} after the end")
            if event["name"] in endings:
                ended.add(mission_id)
        self.assertEqual(ended, set(terminal))


class ArbitrationOrderTests(unittest.IsolatedAsyncioTestCase):
    async def outcome(self, proposals, units):
        logger = FakeLogger()
        controller = MissionController(logger=logger, executor_factories=EXECUTORS)
        await run_tick(controller, 0.0, tuple(units), tuple(proposals))
        missions = {
            item.deduplication_key: (
                item.mission_id,
                item.proposal_id,
                item.status.name,
                item.assigned_unit_tags,
            )
            for item in controller.snapshots()
        }
        events = [
            (
                event["name"],
                event["data"].get("proposal_id"),
                event["data"].get("mission_id"),
                tuple(event["data"].get("unit_tags", ())),
            )
            for event in logger.events
        ]
        return missions, events

    async def test_equal_priorities_decide_the_same_in_every_input_order(self):
        proposals = (proposal("raid:c"), proposal("raid:a"), proposal("raid:b"))
        units = (marine(1), marine(2))
        results = [
            await self.outcome(order, units if index % 2 else reversed(units))
            for index, order in enumerate(itertools.permutations(proposals))
        ]

        for result in results[1:]:
            self.assertEqual(result, results[0])
        missions, _ = results[0]
        self.assertEqual(missions["raid:a"], ("mission-0001", "raid:a#1", "ACTIVE", (1,)))
        self.assertEqual(missions["raid:b"], ("mission-0002", "raid:b#1", "ACTIVE", (2,)))
        self.assertEqual(missions["raid:c"], ("mission-0003", "raid:c#1", "BLOCKED", ()))

    async def test_a_higher_priority_allocates_first_whatever_the_order(self):
        proposals = (proposal("raid:a", priority=50), proposal("raid:z", priority=61))
        for order in itertools.permutations(proposals):
            missions, _ = await self.outcome(order, (marine(1),))
            self.assertEqual(missions["raid:z"][2:], ("ACTIVE", (1,)))
            self.assertEqual(missions["raid:a"][2:], ("BLOCKED", ()))

    async def test_of_two_duplicates_in_one_tick_the_higher_ranked_is_admitted(self):
        low = proposal("raid:a", priority=40, proposal_id="raid:a#low")
        high = proposal("raid:a", priority=70, proposal_id="raid:a#high")
        for order in ((low, high), (high, low)):
            missions, events = await self.outcome(order, (marine(1),))
            self.assertEqual(missions["raid:a"][1], "raid:a#high")
            self.assertEqual(
                [event[1] for event in events if event[0] == "proposal_rejected"],
                ["raid:a#low"],
            )

    async def test_an_earlier_admitted_mission_of_equal_priority_allocates_first(self):
        controller = MissionController(logger=FakeLogger(), executor_factories=EXECUTORS)
        await run_tick(controller, 0.0, (marine(1),), (proposal("raid:z", desired=2),))
        await run_tick(controller, 1.0, (marine(1), marine(2)), (proposal("raid:a"),))

        missions = {item.deduplication_key: item for item in controller.snapshots()}
        self.assertEqual(missions["raid:z"].assigned_unit_tags, (1, 2))
        self.assertIs(missions["raid:a"].status, MissionStatus.BLOCKED)

    def test_every_tie_has_an_explicit_key(self):
        missions = (
            Mission("mission-0002", proposal("raid:a"), admitted_at=3.0),
            Mission("mission-0001", proposal("raid:b"), admitted_at=3.0),
            Mission("mission-0003", proposal("raid:c"), admitted_at=1.0),
            Mission("mission-0004", proposal("raid:d", priority=90), admitted_at=9.0),
        )
        proposals = (
            proposal("raid:b", proposal_id="raid:b#2"),
            proposal("raid:b", proposal_id="raid:b#1"),
            proposal("raid:a"),
            proposal("raid:z", priority=90),
        )
        for order in itertools.permutations(missions):
            self.assertEqual(
                [item.proposal.deduplication_key for item in sorted(order, key=arbitration_key)],
                ["raid:d", "raid:c", "raid:a", "raid:b"],
            )
        for order in itertools.permutations(proposals):
            self.assertEqual(
                [item.proposal_id for item in sorted(order, key=admission_key)],
                ["raid:z#1", "raid:a#1", "raid:b#1", "raid:b#2"],
            )


def signals_from_log(fields: dict[str, Any]) -> MissionSignals:
    objective_id = fields["control_objective"]
    return MissionSignals(
        activity=(
            None
            if fields["activity"] == "FALLBACK"
            else StrategicActivity[fields["activity"]]
        ),
        opportunity=fields["opportunity"],
        urgency=fields["urgency"],
        risk=fields["risk"],
        information_gain=fields["information_gain"],
        control=(
            None
            if objective_id is None
            else ControlMatch(objective_id, fields["control_alignment"])
        ),
        reason=fields["signal_reason"],
    )


class EvaluationLogTests(unittest.TestCase):
    def test_each_logged_evaluation_is_the_one_that_decided_and_replays_exactly(self):
        context = StrategicContext(
            intent=StrategicIntent(
                defense=0.3,
                map_control=0.8,
                harass=0.4,
                information=0.7,
                risk_tolerance=0.5,
            ),
            spatial=SpatialStrategySnapshot(objectives=(region(),)),
            updated_at=30.0,
            revision=4,
        )
        candidates = (
            standing_candidate(1, 30.0),
            candidate(
                "patrol",
                MissionSignals(
                    activity=StrategicActivity.MAP_CONTROL,
                    opportunity=0.6,
                    risk=0.3,
                    information_gain=0.4,
                    control=ControlMatch("region:1", 0.75),
                    reason="frontier",
                ),
                planner="patrol",
            ),
            candidate(
                "raid:a",
                MissionSignals(activity=StrategicActivity.HARASS, risk=0.9),
            ),
            candidate(
                "raid:b",
                MissionSignals(activity=StrategicActivity.HARASS),
            ),
            candidate(
                "scout",
                MissionSignals(
                    activity=StrategicActivity.INFORMATION, urgency=0.95, risk=1.0
                ),
                planner="scouts",
            ),
            candidate(
                "orphan",
                MissionSignals(
                    activity=StrategicActivity.MAP_CONTROL,
                    opportunity=0.5,
                    control=ControlMatch("region:gone", 1.0),
                ),
                planner="patrol",
            ),
        )
        logger = FakeLogger()
        ranker = MissionRanker(logger=logger)

        proposals = {
            item.deduplication_key: item for item in ranker.rank(candidates, context)
        }

        events = [event for event in logger.events if event["name"] == "mission.evaluated"]
        for item, event in zip(candidates, events, strict=True):
            data = json.loads(json.dumps(event["data"], allow_nan=False))
            key = item.draft.deduplication_key
            used = ranker.last_evaluations[key]
            self.assertEqual(data["evaluation"], used.log_fields())
            self.assertEqual(data["signals"], item.signals.log_fields())
            replayed = evaluate_mission(
                signals_from_log(data["signals"]),
                context.intent,
                need=context.need_for(data["signals"]["control_objective"]),
                config=ranker.config,
            )
            self.assertEqual(replayed, used)
            self.assertEqual(data["priority"], used.priority)
            self.assertEqual(data["context_revision"], context.revision)
            self.assertEqual(data["policy_config"], fingerprint(ranker.config))
            if used.viable:
                self.assertEqual(proposals[key].priority, used.priority)
            else:
                self.assertNotIn(key, proposals)
        self.assertEqual(
            {event["data"]["reason"] for event in events},
            {
                "fallback_owner",
                "viable_positive_utility",
                "viable_by_urgency_floor",
                "rejected_negative_raw_utility",
                "rejected_utility_not_above_minimum",
            },
        )


if __name__ == "__main__":
    unittest.main()

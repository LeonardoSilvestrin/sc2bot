"""Behaviors request the concrete units they can use; the allocator enforces
exactly that -- identity, counts, supply, preference, ownership -- and never
decides what a unit type is good for."""

from __future__ import annotations

import dataclasses
import itertools
import unittest
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app.mission_ranking import rank_candidates
from bot.app.mission_registry import DEFAULT_EXECUTOR_FACTORIES
from bot.behavior.defense import DefenseConfig
from bot.behavior.harass.banshee import BansheeHarassConfig
from bot.behavior.harass.reaper import ReaperHarassConfig
from bot.behavior.map_control import MapControlConfig, MapControlPlanner
from bot.behavior.map_control.model import PATROL_UNIT_TYPES
from bot.behavior.scouting import IntelConfig
from bot.behavior.standing import StandingPlanner
from bot.behavior.standing.model import STANDING_ROSTER
from bot.engine.missions import (
    MissionController,
    MissionKind,
    MissionOutcome,
    MissionProposal,
    MissionResult,
    MissionStatus,
    UnitAllocator,
    UnitRequirement,
)
from bot.macro.builds import banshee_cloak, battle_mech, bio_three_one_one
from bot.world.attention import AttentionSnapshot, MapFacts, UnitSnapshot, WorldFacts
from bot.world.awareness import (
    AwarenessSnapshot,
    RelativeStrength,
    SpatialField,
    SpatialFieldSample,
    ThreatAssessment,
)
from bot.world.awareness.bases import BaseSecurityAssessor
from bot.world.awareness.enemy import EnemyAwareness
from tests.fakes import FakeCommands, FakeLogger

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)

# Physical facts only: (supply, flying, weapon hits ground, weapon hits air).
FACTS: dict[UnitTypeId, tuple[float, bool, bool, bool]] = {
    UnitTypeId.MARINE: (1.0, False, True, True),
    UnitTypeId.MARAUDER: (2.0, False, True, False),
    UnitTypeId.REAPER: (1.0, False, True, False),
    UnitTypeId.HELLION: (2.0, False, True, False),
    UnitTypeId.CYCLONE: (3.0, False, True, True),
    UnitTypeId.SIEGETANK: (3.0, False, True, False),
    UnitTypeId.SIEGETANKSIEGED: (3.0, False, True, False),
    UnitTypeId.THOR: (6.0, False, True, True),
    UnitTypeId.VIKINGFIGHTER: (2.0, True, False, True),
    UnitTypeId.BANSHEE: (3.0, True, True, False),
    UnitTypeId.MEDIVAC: (2.0, True, False, False),
    UnitTypeId.SCV: (1.0, False, True, False),
}

# Every type the retired capability profiles counted as a combat unit: the
# fallback owner's explicit roster must still claim each of them.
PREVIOUSLY_PROFILED_COMBAT_TYPES = frozenset(
    {
        UnitTypeId.MARINE,
        UnitTypeId.MARAUDER,
        UnitTypeId.REAPER,
        UnitTypeId.HELLION,
        UnitTypeId.HELLIONTANK,
        UnitTypeId.CYCLONE,
        UnitTypeId.SIEGETANK,
        UnitTypeId.SIEGETANKSIEGED,
        UnitTypeId.THOR,
        UnitTypeId.THORAP,
        UnitTypeId.VIKINGFIGHTER,
        UnitTypeId.VIKINGASSAULT,
        UnitTypeId.BANSHEE,
    }
)
# Produced by a build but deliberately owned by nobody by default.
UNARMED_SUPPORT = frozenset({UnitTypeId.MEDIVAC})


def unit(
    tag: int, unit_type: UnitTypeId, position: Point2 = MAP.own_start
) -> UnitSnapshot:
    supply, flying, ground, air = FACTS[unit_type]
    return UnitSnapshot(
        tag=tag,
        unit_type=unit_type,
        position=position,
        health_percentage=1.0,
        is_flying=flying,
        is_worker=unit_type is UnitTypeId.SCV,
        can_attack_air=air,
        can_attack_ground=ground,
        supply_cost=supply,
    )


def patrol(
    *, desired: int, minimum: int = 0, supply_budget: float | None = None
) -> UnitRequirement:
    config = MapControlConfig()
    return UnitRequirement.combat(
        unit_types=config.unit_types,
        desired=desired,
        minimum=minimum,
        type_desirability=config.type_desirability,
        supply_budget=supply_budget,
    )


def roster(desired: int) -> UnitRequirement:
    return UnitRequirement.combat(
        unit_types=STANDING_ROSTER, desired=desired, minimum=0
    )


def allocate(
    allocator: UnitAllocator,
    mission_id: str,
    requirement: UnitRequirement,
    *,
    priority: int = 40,
    now: float = 0.0,
):
    return allocator.allocate(
        mission_id=mission_id,
        priority=priority,
        requirement=requirement,
        objective=MAP.own_start,
        now=now,
        can_preempt=True,
        commitment_seconds=1.0,
    )


def attention(now: float, units: tuple[UnitSnapshot, ...]) -> AttentionSnapshot:
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=0.0,
            supply_cap=0.0,
            own_units=units,
            enemy_units=(),
            map=MAP,
        )
    )


def awareness_for(current: AttentionSnapshot) -> AwarenessSnapshot:
    return AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=current.world.time,
        bases=BaseSecurityAssessor().update(current.world),
        # One supported, known frontier sample: a patrol worth proposing.
        spatial=SpatialField(
            samples=(
                SpatialFieldSample(
                    MAP.center, friendly_value=0.45, knowledge_confidence=1.0
                ),
            ),
            updated_at=current.world.time,
        ),
    )


class RequirementContractTests(unittest.TestCase):
    def test_a_requirement_names_its_units_and_prices_only_those(self):
        marines = frozenset({UnitTypeId.MARINE})
        with self.assertRaises(ValueError):
            UnitRequirement.combat(unit_types=frozenset(), desired=1, minimum=0)
        with self.assertRaises(ValueError):
            UnitRequirement.combat(
                unit_types=marines,
                desired=1,
                minimum=0,
                type_desirability=((UnitTypeId.BANSHEE, 1.0),),
            )
        with self.assertRaises(ValueError):
            UnitRequirement.combat(
                unit_types=marines, desired=1, minimum=0, supply_budget=0.0
            )
        self.assertFalse(
            {field.name for field in dataclasses.fields(UnitRequirement)}
            & {"capability", "role", "suitability"}
        )

    def test_every_behavior_requests_only_its_supported_unit_types(self):
        defense = DefenseConfig()

        self.assertEqual(
            BansheeHarassConfig().unit_types, frozenset({UnitTypeId.BANSHEE})
        )
        self.assertEqual(
            ReaperHarassConfig().unit_types, frozenset({UnitTypeId.REAPER})
        )
        self.assertIn(UnitTypeId.REAPER, IntelConfig().unit_types)
        self.assertEqual(MapControlConfig().unit_types, PATROL_UNIT_TYPES)
        for table in (
            defense.ground_threat_desirability,
            defense.air_only_threat_desirability,
        ):
            priced = {unit_type for unit_type, _ in table}
            self.assertLessEqual(priced, defense.unit_types)

    def test_the_generic_planners_draft_their_own_roster(self):
        current = attention(
            10.0,
            (
                unit(1, UnitTypeId.MARINE),
                unit(2, UnitTypeId.CYCLONE),
                unit(3, UnitTypeId.CYCLONE),
            ),
        )
        state = awareness_for(current)

        (standing,) = StandingPlanner().propose(current, state)
        (patrolling,) = MapControlPlanner().propose(current, state)

        self.assertEqual(standing.draft.requirement.unit_types, STANDING_ROSTER)
        self.assertEqual(patrolling.draft.requirement.unit_types, PATROL_UNIT_TYPES)


class ConcreteAllocationTests(unittest.TestCase):
    def test_a_behavior_never_receives_an_unsupported_type(self):
        allocator = UnitAllocator()
        allocator.sync(
            (
                unit(1, UnitTypeId.SIEGETANK),
                unit(2, UnitTypeId.BANSHEE),
                unit(3, UnitTypeId.MEDIVAC),
                unit(4, UnitTypeId.SCV),
                unit(5, UnitTypeId.REAPER),
                unit(6, UnitTypeId.MARINE, Point2((80, 80))),
            )
        )

        result = allocate(allocator, "patrol", patrol(desired=6))

        self.assertEqual(result.assigned_tags, (6,))
        for tag in (1, 2, 3, 4, 5):
            self.assertIsNone(allocator.owner_of(tag))

    def test_desired_and_minimum_are_honored(self):
        allocator = UnitAllocator()
        allocator.sync(tuple(unit(tag, UnitTypeId.MARINE) for tag in (1, 2, 3)))

        result = allocate(allocator, "patrol", patrol(desired=2, minimum=1))

        self.assertTrue(result.requirements_satisfied)
        self.assertEqual(result.assigned_tags, (1, 2))
        short = UnitAllocator()
        short.sync((unit(1, UnitTypeId.MARINE),))
        unmet = allocate(short, "patrol", patrol(desired=3, minimum=2))
        self.assertFalse(unmet.requirements_satisfied)
        self.assertIsNone(short.owner_of(1))

    def test_the_budget_binds_before_the_count(self):
        allocator = UnitAllocator()
        allocator.sync(tuple(unit(tag, UnitTypeId.MARINE) for tag in range(1, 7)))

        result = allocate(allocator, "patrol", patrol(desired=6, supply_budget=2.0))

        self.assertEqual(result.assigned_tags, (1, 2))

    def test_the_last_unit_may_overshoot_the_budget(self):
        allocator = UnitAllocator()
        allocator.sync(tuple(unit(tag, UnitTypeId.CYCLONE) for tag in (1, 2, 3)))

        result = allocate(allocator, "patrol", patrol(desired=3, supply_budget=4.0))

        self.assertEqual(result.assigned_tags, (1, 2))

    def test_the_behavior_preference_fills_the_budget_first(self):
        allocator = UnitAllocator()
        allocator.sync(
            (
                unit(1, UnitTypeId.MARINE),
                unit(2, UnitTypeId.CYCLONE),
                unit(3, UnitTypeId.HELLION),
            )
        )

        result = allocate(allocator, "patrol", patrol(desired=3, supply_budget=5.0))

        self.assertEqual(result.assigned_tags, (2, 3))

    def test_a_shrunk_budget_releases_the_least_preferred_units(self):
        allocator = UnitAllocator()
        allocator.sync(
            (
                unit(1, UnitTypeId.MARINE),
                unit(2, UnitTypeId.MARINE),
                unit(3, UnitTypeId.CYCLONE),
                unit(4, UnitTypeId.CYCLONE),
            )
        )
        held = allocate(allocator, "patrol", patrol(desired=4, supply_budget=8.0))
        self.assertEqual(held.assigned_tags, (1, 2, 3, 4))

        result = allocate(
            allocator, "patrol", patrol(desired=4, supply_budget=5.0), now=1.0
        )

        self.assertEqual(result.assigned_tags, (3, 4))
        self.assertEqual(result.released_tags, (1, 2))

    def test_a_preferred_type_beats_a_closer_less_preferred_one(self):
        allocator = UnitAllocator()
        allocator.sync(
            (
                unit(1, UnitTypeId.MARINE, MAP.own_start),
                unit(2, UnitTypeId.HELLION, Point2((80, 80))),
            )
        )

        self.assertEqual(
            allocate(allocator, "patrol", patrol(desired=1)).assigned_tags, (2,)
        )

    def test_an_equal_preference_is_settled_by_distance(self):
        allocator = UnitAllocator()
        allocator.sync(
            (
                unit(1, UnitTypeId.MARINE, Point2((80, 80))),
                unit(2, UnitTypeId.MARAUDER, MAP.own_start),
            )
        )

        self.assertEqual(
            allocate(allocator, "patrol", patrol(desired=1)).assigned_tags, (2,)
        )

    def test_a_shrinking_mission_keeps_its_preferred_unit(self):
        allocator = UnitAllocator()
        allocator.sync(
            (
                unit(1, UnitTypeId.MARINE, MAP.own_start),
                unit(2, UnitTypeId.HELLION, Point2((80, 80))),
            )
        )
        allocate(allocator, "patrol", patrol(desired=2))

        result = allocate(allocator, "patrol", patrol(desired=1), now=1.0)

        self.assertEqual(result.assigned_tags, (2,))
        self.assertEqual(result.released_tags, (1,))

    def test_a_held_unit_is_never_displaced_for_a_better_one(self):
        allocator = UnitAllocator()
        marine, cyclone = unit(1, UnitTypeId.MARINE), unit(2, UnitTypeId.CYCLONE)
        allocator.sync((marine,))
        allocate(allocator, "patrol", patrol(desired=1))
        allocator.sync((marine, cyclone))
        allocate(allocator, "main", roster(2), priority=20)

        result = allocate(allocator, "patrol", patrol(desired=1), now=5.0)

        self.assertEqual(result.assigned_tags, (1,))
        self.assertEqual(result.transfers, ())
        self.assertEqual(allocator.owner_of(2), "main")

    def test_allocation_does_not_depend_on_unit_input_order(self):
        units = (
            unit(1, UnitTypeId.MARINE, Point2((30, 30))),
            unit(2, UnitTypeId.MARAUDER, Point2((30, 30))),
            unit(3, UnitTypeId.HELLION, Point2((20, 20))),
            unit(4, UnitTypeId.CYCLONE, Point2((60, 60))),
            unit(5, UnitTypeId.SIEGETANK, Point2((10, 10))),
            unit(6, UnitTypeId.MARINE, Point2((30, 30))),
        )
        outcomes = set()
        for order in itertools.permutations(units):
            allocator = UnitAllocator()
            allocator.sync(order)
            main = allocate(allocator, "main", roster(6), priority=20)
            share = allocate(
                allocator, "patrol", patrol(desired=6, supply_budget=5.0), now=5.0
            )
            outcomes.add(
                (
                    main.assigned_tags,
                    share.assigned_tags,
                    tuple(transfer.unit_tag for transfer in share.transfers),
                )
            )

        self.assertEqual(len(outcomes), 1)


class RosterCoverageTests(unittest.TestCase):
    def test_no_unit_becomes_ownerless_because_the_profiles_are_gone(self):
        self.assertLessEqual(PREVIOUSLY_PROFILED_COMBAT_TYPES, STANDING_ROSTER)

    def test_every_army_unit_a_build_produces_has_a_roster_decision(self):
        """A produced type joins Standing's roster or is declared support."""

        for build in (battle_mech(), bio_three_one_one(), banshee_cloak()):
            for goal in build.army:
                with self.subTest(build=build.name, unit_type=goal.unit_type.name):
                    self.assertIn(goal.unit_type, STANDING_ROSTER | UNARMED_SUPPORT)


class RunsUntilFinishedExecutor:
    def __init__(self) -> None:
        self.finished = False

    async def step(self, context) -> MissionResult:
        if self.finished:
            return MissionResult(MissionOutcome.COMPLETED, "test_mission_done")
        return MissionResult(MissionOutcome.ACTIVE, "test_mission_running")


def mech_army() -> tuple[UnitSnapshot, ...]:
    return (
        *(unit(tag, UnitTypeId.HELLION) for tag in range(1, 5)),
        *(unit(tag, UnitTypeId.CYCLONE) for tag in (5, 6)),
        *(unit(tag, UnitTypeId.SIEGETANK) for tag in range(7, 11)),
    )


def patrol_planners() -> tuple:
    return (
        MapControlPlanner(config=MapControlConfig(start_after=12.0)),
        StandingPlanner(),
    )


class ControllerHarness(unittest.IsolatedAsyncioTestCase):
    def controller(self, logger: FakeLogger | None = None, factories=None):
        return MissionController(
            logger=logger or FakeLogger(),
            executor_factories=factories or DEFAULT_EXECUTOR_FACTORIES,
        )

    async def advance(
        self,
        controller: MissionController,
        now: float,
        units: tuple[UnitSnapshot, ...],
        *,
        planners: tuple = (),
        proposals: tuple[MissionProposal, ...] = (),
    ) -> None:
        current = attention(now, units)
        awareness = awareness_for(current)
        planned = tuple(
            proposal
            for planner in planners
            for proposal in rank_candidates(planner.propose(current, awareness))
        )
        await controller.tick(
            attention=current,
            awareness=awareness,
            proposals=(*proposals, *planned),
            commands=FakeCommands(),
        )

    def owned_types(
        self,
        controller: MissionController,
        mission_key: str,
        units: tuple[UnitSnapshot, ...],
    ) -> list[UnitTypeId]:
        mission = controller.board.live_for_key(mission_key)
        assert mission is not None
        by_tag = {item.tag: item for item in units}
        return sorted(
            (by_tag[tag].unit_type for tag in mission.assigned_unit_tags),
            key=lambda unit_type: unit_type.name,
        )


class GenericBehaviorAllocationTests(ControllerHarness):
    async def run_patrol(self, units: tuple[UnitSnapshot, ...]) -> MissionController:
        controller = self.controller()
        planners = patrol_planners()
        await self.advance(controller, 10.0, units, planners=planners)
        await self.advance(controller, 12.0, units, planners=planners)
        return controller

    async def test_a_mech_army_patrols_with_patrol_units_and_keeps_tanks_home(self):
        units = mech_army()
        controller = await self.run_patrol(units)

        # 26 combat supply, a fifth of it patrols: two Cyclones cover the 5.2
        # budget, and no Tank is taken off the line.
        self.assertEqual(
            self.owned_types(controller, "map_control:patrol", units),
            [UnitTypeId.CYCLONE, UnitTypeId.CYCLONE],
        )
        main = self.owned_types(controller, "hold_rally:main_army", units)
        self.assertEqual(main.count(UnitTypeId.SIEGETANK), 4)
        self.assertEqual(len(main), 8)
        live = controller.board.live_for_key("map_control:patrol")
        assert live is not None
        self.assertEqual(live.proposal.requirement.unit_types, PATROL_UNIT_TYPES)
        self.assertEqual(live.proposal.requirement.supply_budget, 5.2)

    async def test_a_bio_army_patrols_with_its_bio_and_owns_everything(self):
        units = (
            *(unit(tag, UnitTypeId.MARINE) for tag in range(1, 11)),
            unit(11, UnitTypeId.MARAUDER),
            unit(12, UnitTypeId.MARAUDER),
            unit(13, UnitTypeId.SIEGETANK),
            unit(14, UnitTypeId.SIEGETANK),
        )
        controller = await self.run_patrol(units)

        patrolling = self.owned_types(controller, "map_control:patrol", units)
        self.assertTrue(patrolling)
        self.assertLessEqual(
            set(patrolling), {UnitTypeId.MARINE, UnitTypeId.MARAUDER}
        )
        for item in units:
            with self.subTest(tag=item.tag):
                self.assertIsNotNone(controller.allocator.owner_of(item.tag))

    async def test_standing_receives_every_unused_roster_unit_and_nothing_else(self):
        units = (
            unit(1, UnitTypeId.MARINE),
            unit(2, UnitTypeId.MARAUDER),
            unit(3, UnitTypeId.REAPER),
            unit(4, UnitTypeId.HELLION),
            unit(5, UnitTypeId.CYCLONE),
            unit(6, UnitTypeId.SIEGETANKSIEGED),
            unit(7, UnitTypeId.THOR),
            unit(8, UnitTypeId.VIKINGFIGHTER),
            unit(9, UnitTypeId.BANSHEE),
            unit(10, UnitTypeId.MEDIVAC),
            unit(11, UnitTypeId.SCV),
        )
        controller = self.controller()
        planner = StandingPlanner()

        await self.advance(controller, 10.0, units, planners=(planner,))

        main = controller.board.live_for_key("hold_rally:main_army")
        self.assertEqual(main.assigned_unit_tags, tuple(range(1, 10)))
        assert planner.last_assessment is not None
        self.assertEqual(planner.last_assessment.combat_units, 9)
        self.assertIsNone(controller.allocator.owner_of(10))
        self.assertIsNone(controller.allocator.owner_of(11))

    async def test_a_specialized_raid_takes_its_own_unit_and_gives_it_back(self):
        units = (unit(1, UnitTypeId.MARINE), unit(2, UnitTypeId.BANSHEE))
        raid_executor = RunsUntilFinishedExecutor()
        factories: dict[MissionKind, Any] = dict(DEFAULT_EXECUTOR_FACTORIES)
        factories[MissionKind.AIR_HARASS] = lambda mission, now: raid_executor
        controller = self.controller(factories=factories)
        raid = MissionProposal(
            proposal_id="raid:12",
            deduplication_key="air_harass:test",
            planner="test_raid",
            kind=MissionKind.AIR_HARASS,
            priority=62,
            target_key="enemy_base",
            target=MAP.enemy_starts[0],
            reason="test",
            requirement=UnitRequirement.combat(
                unit_types=frozenset({UnitTypeId.BANSHEE}), desired=2, minimum=1
            ),
            created_at=12.0,
            can_preempt=True,
            commitment_seconds=1.0,
        )

        await self.advance(controller, 10.0, units, planners=(StandingPlanner(),))
        main = controller.board.live_for_key("hold_rally:main_army")
        self.assertEqual(main.assigned_unit_tags, (1, 2))

        await self.advance(controller, 12.0, units, proposals=(raid,))
        live_raid = controller.board.live_for_key("air_harass:test")
        self.assertEqual(live_raid.assigned_unit_tags, (2,))
        self.assertEqual(main.assigned_unit_tags, (1,))

        raid_executor.finished = True
        await self.advance(controller, 13.0, units)
        self.assertEqual(live_raid.status, MissionStatus.COMPLETED)
        self.assertEqual(main.assigned_unit_tags, (1, 2))

    async def test_defense_borrows_tanks_from_a_mixed_squad_and_returns_them(self):
        units = (
            *(unit(tag, UnitTypeId.MARINE) for tag in (1, 2, 3)),
            unit(4, UnitTypeId.SIEGETANK),
            unit(5, UnitTypeId.SIEGETANK),
        )
        defense_executor = RunsUntilFinishedExecutor()
        factories: dict[MissionKind, Any] = dict(DEFAULT_EXECUTOR_FACTORIES)
        factories[MissionKind.DEFENSE] = lambda mission, now: defense_executor
        controller = self.controller(factories=factories)
        defense = MissionProposal(
            proposal_id="defense:12",
            deduplication_key="defense:own_base",
            planner="test_defense",
            kind=MissionKind.DEFENSE,
            priority=90,
            target_key="own_base",
            target=MAP.own_start,
            reason="test",
            requirement=UnitRequirement.combat(
                unit_types=frozenset({UnitTypeId.MARINE, UnitTypeId.SIEGETANK}),
                desired=2,
                minimum=1,
                type_desirability=(
                    (UnitTypeId.SIEGETANK, 1.0),
                    (UnitTypeId.MARINE, 0.6),
                ),
            ),
            created_at=12.0,
            can_preempt=True,
            commitment_seconds=1.0,
        )

        await self.advance(controller, 10.0, units, planners=(StandingPlanner(),))
        await self.advance(controller, 12.0, units, proposals=(defense,))

        live_defense = controller.board.live_for_key("defense:own_base")
        self.assertEqual(live_defense.assigned_unit_tags, (4, 5))
        squad = controller.squads.get("main_army")
        self.assertEqual(squad.current_mission_id, live_defense.mission_id)

        defense_executor.finished = True
        await self.advance(controller, 13.0, units)

        self.assertEqual(live_defense.status, MissionStatus.COMPLETED)
        main = controller.board.live_for_key("hold_rally:main_army")
        self.assertEqual(main.assigned_unit_tags, (1, 2, 3, 4, 5))
        self.assertEqual(squad.current_mission_id, main.mission_id)
        self.assertEqual(squad.member_tags, {1, 2, 3, 4, 5})

    async def test_a_preempted_patrol_member_shrinks_the_budget_it_backfills(self):
        """A Cyclone away on defense leaves no hole the patrol refills."""

        units = mech_army()
        defense_executor = RunsUntilFinishedExecutor()
        factories: dict[MissionKind, Any] = dict(DEFAULT_EXECUTOR_FACTORIES)
        factories[MissionKind.DEFENSE] = lambda mission, now: defense_executor
        controller = self.controller(factories=factories)
        planners = patrol_planners()
        await self.advance(controller, 10.0, units, planners=planners)
        await self.advance(controller, 12.0, units, planners=planners)
        patrolling = controller.board.live_for_key("map_control:patrol")
        self.assertEqual(patrolling.assigned_unit_tags, (5, 6))

        defense = MissionProposal(
            proposal_id="defense:14",
            deduplication_key="defense:own_base",
            planner="test_defense",
            kind=MissionKind.DEFENSE,
            priority=90,
            target_key="own_base",
            target=MAP.own_start,
            reason="test",
            requirement=UnitRequirement.combat(
                unit_types=frozenset({UnitTypeId.CYCLONE}), desired=1, minimum=1
            ),
            created_at=14.0,
            can_preempt=True,
            commitment_seconds=1.0,
        )
        await self.advance(controller, 14.0, units, proposals=(defense,))

        self.assertEqual(len(patrolling.assigned_unit_tags), 1)
        self.assertEqual(controller.squads.get("map_control").member_tags, {5, 6})


if __name__ == "__main__":
    unittest.main()

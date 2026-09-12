"""Generic missions ask for a role; the allocator scores every unit that exists."""

from __future__ import annotations

import dataclasses
import inspect
import unittest
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app.mission_registry import DEFAULT_EXECUTOR_FACTORIES
from bot.behavior.map_control import MapControlConfig, MapControlPlanner
from bot.behavior.standing import StandingPlanner
from bot.domain import COMBAT_UNIT_TYPES, capabilities_for, score_unit_for_requirement
from bot.engine.missions import (
    CombatRole,
    MissionController,
    MissionKind,
    MissionMode,
    MissionOutcome,
    MissionProposal,
    MissionResult,
    MissionStatus,
    UnitAllocator,
    UnitRequirement,
)
from bot.world.attention import AttentionSnapshot, MapFacts, UnitSnapshot, WorldFacts
from bot.world.awareness import (
    AwarenessSnapshot,
    MacroPosture,
    RelativeStrength,
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

SUPPLY = {
    UnitTypeId.MARINE: 1.0,
    UnitTypeId.MARAUDER: 2.0,
    UnitTypeId.REAPER: 1.0,
    UnitTypeId.HELLION: 2.0,
    UnitTypeId.CYCLONE: 3.0,
    UnitTypeId.SIEGETANK: 3.0,
    UnitTypeId.SIEGETANKSIEGED: 3.0,
    UnitTypeId.THOR: 6.0,
    UnitTypeId.VIKINGFIGHTER: 2.0,
    UnitTypeId.BANSHEE: 3.0,
    UnitTypeId.MEDIVAC: 2.0,
    UnitTypeId.SCV: 1.0,
}


def unit(
    tag: int, unit_type: UnitTypeId, position: Point2 = MAP.own_start
) -> UnitSnapshot:
    profile = capabilities_for(unit_type)
    return UnitSnapshot(
        tag=tag,
        unit_type=unit_type,
        position=position,
        health_percentage=1.0,
        is_flying=profile is not None and profile.is_flying,
        is_worker=unit_type is UnitTypeId.SCV,
        can_attack_air=profile is not None and profile.attacks_air,
        can_attack_ground=profile is not None and profile.attacks_ground,
        supply_cost=SUPPLY[unit_type],
    )


def patrol_requirement(
    *, desired: int, minimum: int = 0, supply_budget: float | None = None
) -> UnitRequirement:
    return UnitRequirement.for_role(
        CombatRole.MOBILE_CONTROL,
        desired=desired,
        minimum=minimum,
        supply_budget=supply_budget,
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


class RoleRequirementTests(unittest.TestCase):
    def test_a_role_request_is_a_capability_and_nothing_else(self):
        requirement = patrol_requirement(desired=2)

        self.assertIs(requirement.capability, CombatRole.MOBILE_CONTROL.requirement)
        self.assertEqual(requirement.unit_types, frozenset())
        self.assertTrue(requirement.exclude_resource_carriers)
        self.assertTrue(requirement.exclude_constructors)
        self.assertEqual(
            set(inspect.signature(UnitRequirement.for_role).parameters),
            {"role", "desired", "minimum", "minimum_health", "supply_budget"},
        )
        self.assertNotIn(
            "preferred_unit_types",
            {field.name for field in dataclasses.fields(UnitRequirement)},
        )

    def test_utility_is_exactly_the_suitability(self):
        requirement = patrol_requirement(desired=1)

        for unit_type in (UnitTypeId.MARINE, UnitTypeId.HELLION, UnitTypeId.CYCLONE):
            with self.subTest(unit_type=unit_type.name):
                self.assertEqual(
                    requirement.utility_for(unit(1, unit_type)),
                    score_unit_for_requirement(
                        unit_type, CombatRole.MOBILE_CONTROL.requirement
                    ).score,
                )

    def test_every_combat_unit_is_scored_whichever_build_produced_it(self):
        requirement = patrol_requirement(desired=1)

        for unit_type in (
            UnitTypeId.MARINE,
            UnitTypeId.MARAUDER,
            UnitTypeId.HELLION,
            UnitTypeId.CYCLONE,
            UnitTypeId.BANSHEE,
            UnitTypeId.SIEGETANK,
        ):
            with self.subTest(unit_type=unit_type.name):
                candidate = unit(1, unit_type)
                self.assertTrue(requirement.matches(candidate))
                self.assertGreater(requirement.utility_for(candidate), 0.0)
        # Physics and profiles, not a unit list, keep these out.
        self.assertFalse(requirement.matches(unit(1, UnitTypeId.VIKINGFIGHTER)))
        self.assertFalse(requirement.matches(unit(1, UnitTypeId.MEDIVAC)))

    def test_a_capability_requirement_lists_no_unit_and_prices_none_by_hand(self):
        role = CombatRole.MOBILE_CONTROL.requirement
        with self.assertRaises(ValueError):
            UnitRequirement(
                unit_types=frozenset({UnitTypeId.MARINE}),
                desired=1,
                minimum=0,
                capability=role,
            )
        with self.assertRaises(ValueError):
            UnitRequirement(
                unit_types=frozenset(),
                desired=1,
                minimum=0,
                capability=role,
                type_desirability=((UnitTypeId.MARINE, 0.5),),
            )
        with self.assertRaises(ValueError):
            patrol_requirement(desired=1, supply_budget=0.0)

    def test_the_fallback_claim_is_every_combat_unit_at_equal_worth(self):
        requirement = UnitRequirement.any_combat_unit(desired=3, minimum=0)

        self.assertIsNone(requirement.capability)
        self.assertEqual(requirement.unit_types, COMBAT_UNIT_TYPES)
        for unit_type in (UnitTypeId.MARINE, UnitTypeId.THOR, UnitTypeId.VIKINGFIGHTER):
            with self.subTest(unit_type=unit_type.name):
                self.assertTrue(requirement.matches(unit(1, unit_type)))
                self.assertEqual(requirement.utility_for(unit(1, unit_type)), 1.0)
        self.assertFalse(requirement.matches(unit(1, UnitTypeId.MEDIVAC)))
        self.assertFalse(requirement.matches(unit(1, UnitTypeId.SCV)))


class SuitabilityAllocationTests(unittest.TestCase):
    def test_the_more_suitable_unit_wins_over_a_closer_less_suitable_one(self):
        allocator = UnitAllocator()
        allocator.sync(
            (
                unit(1, UnitTypeId.MARINE, MAP.own_start),
                unit(2, UnitTypeId.HELLION, Point2((80, 80))),
            )
        )

        result = allocate(allocator, "patrol", patrol_requirement(desired=1))

        self.assertEqual(result.assigned_tags, (2,))

    def test_near_equal_suitability_is_settled_by_distance(self):
        allocator = UnitAllocator()
        allocator.sync(
            (
                unit(1, UnitTypeId.MARINE, Point2((80, 80))),
                unit(2, UnitTypeId.MARAUDER, MAP.own_start),
            )
        )

        result = allocate(allocator, "patrol", patrol_requirement(desired=1))

        self.assertEqual(result.assigned_tags, (2,))

    def test_marines_hellions_and_cyclones_are_ranked_side_by_side(self):
        army = (
            unit(1, UnitTypeId.MARINE),
            unit(2, UnitTypeId.HELLION),
            unit(3, UnitTypeId.CYCLONE),
        )
        for desired, expected in ((1, (3,)), (2, (2, 3)), (3, (1, 2, 3))):
            with self.subTest(desired=desired):
                allocator = UnitAllocator()
                allocator.sync(army)

                result = allocate(
                    allocator, "patrol", patrol_requirement(desired=desired)
                )

                self.assertEqual(result.assigned_tags, expected)

    def test_a_unit_of_an_earlier_composition_still_fills_the_role(self):
        allocator = UnitAllocator()
        allocator.sync(tuple(unit(tag, UnitTypeId.MARINE) for tag in (1, 2, 3)))

        result = allocate(
            allocator, "patrol", patrol_requirement(desired=2, minimum=1)
        )

        self.assertTrue(result.requirements_satisfied)
        self.assertEqual(result.assigned_tags, (1, 2))

    def test_a_poor_fit_is_taken_only_when_nothing_better_exists(self):
        allocator = UnitAllocator()
        allocator.sync((unit(1, UnitTypeId.SIEGETANK), unit(2, UnitTypeId.MARINE)))
        self.assertEqual(
            allocate(allocator, "patrol", patrol_requirement(desired=1)).assigned_tags,
            (2,),
        )

        alone = UnitAllocator()
        alone.sync((unit(1, UnitTypeId.SIEGETANK),))
        self.assertEqual(
            allocate(alone, "patrol", patrol_requirement(desired=1)).assigned_tags,
            (1,),
        )

    def test_a_zero_suitability_unit_is_never_requested_even_when_alone(self):
        allocator = UnitAllocator()
        allocator.sync((unit(1, UnitTypeId.MARINE),))

        result = allocate(
            allocator,
            "anchor",
            UnitRequirement.for_role(CombatRole.SIEGE_ANCHOR, desired=1, minimum=1),
        )

        self.assertFalse(result.requirements_satisfied)
        self.assertIsNone(allocator.owner_of(1))

    def test_a_shrinking_mission_keeps_its_best_suited_unit(self):
        allocator = UnitAllocator()
        allocator.sync(
            (
                unit(1, UnitTypeId.MARINE, MAP.own_start),
                unit(2, UnitTypeId.HELLION, Point2((80, 80))),
            )
        )
        allocate(allocator, "patrol", patrol_requirement(desired=2))

        result = allocate(allocator, "patrol", patrol_requirement(desired=1), now=1.0)

        self.assertEqual(result.assigned_tags, (2,))
        self.assertEqual(result.released_tags, (1,))


class SupplyBudgetTests(unittest.TestCase):
    def test_the_budget_binds_before_the_count(self):
        allocator = UnitAllocator()
        allocator.sync(tuple(unit(tag, UnitTypeId.MARINE) for tag in range(1, 7)))

        result = allocate(
            allocator, "patrol", patrol_requirement(desired=6, supply_budget=2.0)
        )

        self.assertEqual(result.assigned_tags, (1, 2))

    def test_the_last_unit_may_overshoot_the_budget(self):
        allocator = UnitAllocator()
        allocator.sync(tuple(unit(tag, UnitTypeId.CYCLONE) for tag in (1, 2, 3)))

        result = allocate(
            allocator, "patrol", patrol_requirement(desired=3, supply_budget=4.0)
        )

        self.assertEqual(result.assigned_tags, (1, 2))

    def test_different_units_fill_the_same_budget_by_suitability(self):
        allocator = UnitAllocator()
        allocator.sync(
            (
                unit(1, UnitTypeId.MARINE),
                unit(2, UnitTypeId.CYCLONE),
                unit(3, UnitTypeId.HELLION),
            )
        )

        result = allocate(
            allocator, "patrol", patrol_requirement(desired=3, supply_budget=5.0)
        )

        self.assertEqual(result.assigned_tags, (2, 3))

    def test_a_shrunk_budget_releases_the_least_suitable_units(self):
        allocator = UnitAllocator()
        allocator.sync(
            (
                unit(1, UnitTypeId.MARINE),
                unit(2, UnitTypeId.MARINE),
                unit(3, UnitTypeId.CYCLONE),
                unit(4, UnitTypeId.CYCLONE),
            )
        )
        held = allocate(
            allocator, "patrol", patrol_requirement(desired=4, supply_budget=8.0)
        )
        self.assertEqual(held.assigned_tags, (1, 2, 3, 4))

        result = allocate(
            allocator,
            "patrol",
            patrol_requirement(desired=4, supply_budget=5.0),
            now=1.0,
        )

        self.assertEqual(result.assigned_tags, (3, 4))
        self.assertEqual(result.released_tags, (1, 2))


class UpgradeHysteresisTests(unittest.TestCase):
    """A held unit only moves for a clearly better one -- never for noise."""

    def setup_patrol_and_main(
        self, patrol_type: UnitTypeId, main_type: UnitTypeId
    ) -> UnitAllocator:
        allocator = UnitAllocator()
        patrol_unit, main_unit = unit(1, patrol_type), unit(2, main_type)
        allocator.sync((patrol_unit,))
        allocate(allocator, "patrol", patrol_requirement(desired=1), priority=40)
        allocator.sync((patrol_unit, main_unit))
        allocate(allocator, "main", main_requirement(2), priority=20)
        self.assertEqual(allocator.owner_of(1), "patrol")
        self.assertEqual(allocator.owner_of(2), "main")
        return allocator

    def test_a_small_suitability_difference_never_moves_a_unit(self):
        allocator = self.setup_patrol_and_main(UnitTypeId.MARAUDER, UnitTypeId.MARINE)

        for now in (5.0, 10.0, 15.0):
            result = allocate(
                allocator, "patrol", patrol_requirement(desired=1), now=now
            )
            self.assertEqual(result.assigned_tags, (1,))
            self.assertEqual(result.upgrades, ())
            self.assertEqual(result.transfers, ())
        self.assertEqual(allocator.owner_of(2), "main")

    def test_a_clearly_better_unit_is_swapped_in_and_the_donor_takes_the_other(self):
        allocator = self.setup_patrol_and_main(UnitTypeId.MARINE, UnitTypeId.CYCLONE)

        result = allocate(allocator, "patrol", patrol_requirement(desired=1), now=5.0)

        self.assertEqual(result.assigned_tags, (2,))
        self.assertEqual(result.released_tags, (1,))
        self.assertEqual(len(result.upgrades), 1)
        upgrade = result.upgrades[0]
        self.assertGreaterEqual(
            upgrade.acquired_utility - upgrade.released_utility,
            allocator.upgrade_margin,
        )
        self.assertEqual(result.transfers[0].from_mission_id, "main")

        allocator.release_units("patrol", result.released_tags)
        donor = allocate(allocator, "main", main_requirement(2), priority=20, now=5.0)
        self.assertEqual(donor.assigned_tags, (1,))

    def test_a_free_unit_is_never_an_upgrade_source(self):
        """Releasing a held unit for a free one could leave it ownerless."""

        allocator = UnitAllocator()
        marine = unit(1, UnitTypeId.MARINE)
        allocator.sync((marine,))
        requirement = patrol_requirement(desired=1)
        allocate(allocator, "patrol", requirement)
        allocator.sync((marine, unit(2, UnitTypeId.CYCLONE)))

        result = allocate(allocator, "patrol", requirement, now=5.0)

        self.assertEqual(result.assigned_tags, (1,))
        self.assertEqual(result.upgrades, ())
        self.assertIsNone(allocator.owner_of(2))

    def test_an_upgrade_under_a_supply_budget_settles_back_within_it(self):
        allocator = UnitAllocator()
        marines = tuple(unit(tag, UnitTypeId.MARINE) for tag in (1, 2, 3))
        requirement = patrol_requirement(desired=4, supply_budget=3.0)
        allocator.sync(marines)
        allocate(allocator, "patrol", requirement)
        allocator.sync((*marines, unit(4, UnitTypeId.CYCLONE)))
        allocate(allocator, "main", main_requirement(4), priority=20)

        swapped = allocate(allocator, "patrol", requirement, now=5.0)
        self.assertEqual(len(swapped.upgrades), 1)
        self.assertEqual(swapped.upgrades[0].acquired_tag, 4)
        allocator.release_units("patrol", swapped.released_tags)

        settled = allocate(allocator, "patrol", requirement, now=6.0)

        self.assertEqual(settled.assigned_tags, (4,))
        self.assertEqual(settled.upgrades, ())

    def test_identity_requirements_keep_their_units_exactly_as_before(self):
        allocator = UnitAllocator()
        marine, tank = unit(1, UnitTypeId.MARINE), unit(2, UnitTypeId.SIEGETANK)
        identity = UnitRequirement.combat(
            unit_types=frozenset({UnitTypeId.MARINE, UnitTypeId.SIEGETANK}),
            desired=1,
            minimum=1,
            type_desirability=((UnitTypeId.SIEGETANK, 1.0), (UnitTypeId.MARINE, 0.2)),
        )
        allocator.sync((marine,))
        allocate(allocator, "defense", identity, priority=85)
        allocator.sync((marine, tank))
        allocate(allocator, "main", main_requirement(2), priority=20)

        result = allocate(allocator, "defense", identity, priority=85, now=5.0)

        self.assertEqual(result.assigned_tags, (1,))
        self.assertEqual(result.upgrades, ())


def main_requirement(desired: int) -> UnitRequirement:
    return UnitRequirement.any_combat_unit(desired=desired, minimum=0)


def awareness_for(current: AttentionSnapshot) -> AwarenessSnapshot:
    return AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=current.world.time,
        macro_posture=MacroPosture.BALANCED,
        bases=BaseSecurityAssessor().update(current.world),
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


class RunsUntilFinishedExecutor:
    def __init__(self) -> None:
        self.finished = False

    async def step(self, context) -> MissionResult:
        if self.finished:
            return MissionResult(MissionOutcome.COMPLETED, "test_mission_done")
        return MissionResult(MissionOutcome.ACTIVE, "test_mission_running")


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
            for proposal in planner.propose(current, awareness)
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

    def assert_every_combat_unit_owned(
        self, controller: MissionController, units: tuple[UnitSnapshot, ...]
    ) -> None:
        for item in units:
            if item.unit_type in COMBAT_UNIT_TYPES:
                with self.subTest(tag=item.tag, unit_type=item.unit_type.name):
                    self.assertIsNotNone(controller.allocator.owner_of(item.tag))


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


class MapControlOnAnyArmyTests(ControllerHarness):
    async def run_patrol(
        self, units: tuple[UnitSnapshot, ...], logger: FakeLogger | None = None
    ) -> MissionController:
        controller = self.controller(logger)
        planners = patrol_planners()
        await self.advance(controller, 10.0, units, planners=planners)
        await self.advance(controller, 12.0, units, planners=planners)
        return controller

    async def test_a_mech_army_patrols_with_its_most_mobile_units(self):
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
        live_patrol = controller.board.live_for_key("map_control:patrol")
        assert live_patrol is not None
        proposal = live_patrol.proposal
        self.assertIs(
            proposal.requirement.capability, CombatRole.MOBILE_CONTROL.requirement
        )
        self.assertEqual(proposal.requirement.supply_budget, 5.2)

    async def test_a_bio_army_patrols_with_its_bio(self):
        units = (
            *(unit(tag, UnitTypeId.MARINE) for tag in range(1, 11)),
            unit(11, UnitTypeId.MARAUDER),
            unit(12, UnitTypeId.MARAUDER),
            unit(13, UnitTypeId.SIEGETANK),
            unit(14, UnitTypeId.SIEGETANK),
        )
        controller = await self.run_patrol(units)

        patrol = self.owned_types(controller, "map_control:patrol", units)
        self.assertTrue(patrol)
        self.assertLessEqual(set(patrol), {UnitTypeId.MARINE, UnitTypeId.MARAUDER})
        self.assert_every_combat_unit_owned(controller, units)

    async def test_marines_hellions_and_cyclones_compete_for_one_patrol(self):
        logger = FakeLogger()
        units = (
            *(unit(tag, UnitTypeId.MARINE) for tag in range(1, 7)),
            unit(7, UnitTypeId.HELLION),
            unit(8, UnitTypeId.HELLION),
            unit(9, UnitTypeId.CYCLONE),
            unit(10, UnitTypeId.SIEGETANK),
            unit(11, UnitTypeId.SIEGETANK),
        )
        controller = await self.run_patrol(units, logger)

        # 19 supply -> a 3.8 budget: the Cyclone, then a Hellion.
        self.assertEqual(
            self.owned_types(controller, "map_control:patrol", units),
            [UnitTypeId.CYCLONE, UnitTypeId.HELLION],
        )
        patrol = controller.board.live_for_key("map_control:patrol")
        assert patrol is not None
        change = next(
            event["data"]
            for event in logger.events
            if event["name"] == "capability_composition_changed"
            and event["data"]["mission_id"] == patrol.mission_id
        )
        utilities = {
            line["unit_type"]: line["utility"] for line in change["candidates"]
        }
        for name in ("MARINE", "HELLION", "CYCLONE"):
            with self.subTest(unit_type=name):
                self.assertGreater(utilities[name], 0.0)
        self.assertEqual(
            [line["unit_type"] for line in change["candidates"]][:3],
            ["CYCLONE", "HELLION", "MARINE"],
        )

    async def test_the_assignment_is_explained_when_the_composition_changes(self):
        logger = FakeLogger()
        controller = await self.run_patrol(mech_army(), logger)
        patrol = controller.board.live_for_key("map_control:patrol")
        assert patrol is not None

        changes = [
            event["data"]
            for event in logger.events
            if event["name"] == "capability_composition_changed"
            and event["data"]["mission_id"] == patrol.mission_id
        ]
        self.assertEqual(len(changes), 1)
        change = changes[0]
        self.assertEqual(change["role"], "MOBILE_CONTROL")
        self.assertEqual(change["composition"], {"CYCLONE": 2})
        self.assertEqual(change["new_unit_types"], ["CYCLONE"])
        self.assertEqual(change["supply"], 6.0)
        self.assertEqual(change["supply_budget"], 5.2)
        candidates = {line["unit_type"]: line for line in change["candidates"]}
        self.assertEqual(
            [line["unit_type"] for line in change["candidates"]][:2],
            ["CYCLONE", "HELLION"],
        )
        self.assertEqual(candidates["CYCLONE"]["capabilities"]["mobility"], 0.75)
        # A poor fit, ranked last -- not a rejected one.
        self.assertNotIn("rejection", candidates["SIEGETANK"])
        self.assertLess(candidates["SIEGETANK"]["utility"], 0.2)

        # Another unchanged tick explains nothing new.
        await self.advance(controller, 13.0, mech_army())
        self.assertEqual(
            sum(
                event["name"] == "capability_composition_changed"
                and event["data"]["mission_id"] == patrol.mission_id
                for event in logger.events
            ),
            1,
        )

    async def test_no_suitable_candidate_is_reported_once(self):
        logger = FakeLogger()
        controller = self.controller(logger)
        vikings = tuple(unit(tag, UnitTypeId.VIKINGFIGHTER) for tag in (1, 2))

        def patrol(now: float) -> MissionProposal:
            return MissionProposal(
                proposal_id=f"test_patrol:{now}",
                deduplication_key="map_control:patrol",
                planner="test_patrol",
                kind=MissionKind.MAP_CONTROL,
                priority=40,
                target_key="map_control:patrol",
                target=MAP.center,
                reason="test",
                requirement=patrol_requirement(desired=2),
                created_at=now,
                can_preempt=True,
                commitment_seconds=1.0,
                mode=MissionMode.STANDING,
            )

        await self.advance(controller, 10.0, vikings, proposals=(patrol(10.0),))
        await self.advance(controller, 11.0, vikings, proposals=(patrol(11.0),))

        reports = [
            event["data"]
            for event in logger.events
            if event["name"] == "capability_no_suitable_candidates"
        ]
        self.assertEqual(len(reports), 1)
        self.assertEqual(
            reports[0]["candidates"][0]["rejection"], "cannot_attack_ground"
        )

        units = (*vikings, unit(3, UnitTypeId.MARINE))
        await self.advance(controller, 12.0, units, proposals=(patrol(12.0),))
        change = next(
            event["data"]
            for event in logger.events
            if event["name"] == "capability_composition_changed"
        )
        self.assertEqual(change["new_unit_types"], ["MARINE"])


class BuildTransitionTests(ControllerHarness):
    async def test_a_bio_to_mech_transition_needs_no_transition_rule(self):
        """Production changes; the mission system just keeps scoring."""

        logger = FakeLogger()
        controller = self.controller(logger)
        planners = patrol_planners()
        bio = (
            *(unit(tag, UnitTypeId.MARINE) for tag in range(1, 9)),
            unit(9, UnitTypeId.SIEGETANK),
            unit(10, UnitTypeId.SIEGETANK),
        )
        await self.advance(controller, 10.0, bio, planners=planners)
        await self.advance(controller, 12.0, bio, planners=planners)
        patrol = controller.board.live_for_key("map_control:patrol")
        main = controller.board.live_for_key("hold_rally:main_army")
        self.assertEqual(
            set(self.owned_types(controller, "map_control:patrol", bio)),
            {UnitTypeId.MARINE},
        )

        # Macro starts producing Mech; every Marine is still alive.
        mixed = (
            *bio,
            unit(11, UnitTypeId.HELLION),
            unit(12, UnitTypeId.HELLION),
            unit(13, UnitTypeId.CYCLONE),
            unit(14, UnitTypeId.CYCLONE),
        )
        for now in (20.0, 23.0, 24.0, 27.0, 28.0):
            await self.advance(controller, now, mixed, planners=planners)
            self.assert_every_combat_unit_owned(controller, mixed)

        self.assertIs(controller.board.live_for_key("map_control:patrol"), patrol)
        self.assertIs(controller.board.live_for_key("hold_rally:main_army"), main)
        self.assertEqual(
            self.owned_types(controller, "map_control:patrol", mixed),
            [UnitTypeId.CYCLONE, UnitTypeId.CYCLONE],
        )
        # The Marines were not rejected: they went back to the main army.
        for tag in range(1, 9):
            self.assertEqual(controller.allocator.owner_of(tag), main.mission_id)
        self.assertTrue(
            any(event["name"] == "units_upgraded" for event in logger.events)
        )


class StandingFallbackTests(ControllerHarness):
    async def test_standing_holds_every_combat_unit_any_build_produced(self):
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
        self.assertIsNone(main.proposal.requirement.capability)

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


class SquadSupplyBudgetTests(ControllerHarness):
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
        patrol = controller.board.live_for_key("map_control:patrol")
        self.assertEqual(patrol.assigned_unit_tags, (5, 6))

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

        self.assertEqual(len(patrol.assigned_unit_tags), 1)
        self.assertEqual(
            controller.squads.get("map_control").member_tags, {5, 6}
        )


if __name__ == "__main__":
    unittest.main()

"""Harass target selection, from the enemy model to the mission.

    Enemy Awareness -> unit-specific assessment -> ranked targets
                    -> planner (held target, retarget margin) -> harass mission

Most fixtures state Awareness readings directly, so each test says exactly
what the enemy model believes and checks only how a raid interprets it.
"""

from __future__ import annotations

import unittest
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.app.mission_registry import build_executor_factories
from bot.behavior.harass.banshee import (
    BansheeHarassAssessment,
    BansheeHarassAssessor,
    BansheeHarassPlanner,
    BansheeTargetAssessment,
    BansheeTargetHeuristics,
)
from bot.behavior.harass.reaper import (
    ReaperHarassAssessment,
    ReaperHarassAssessor,
    ReaperHarassPlanner,
    ReaperTargetAssessment,
)
from bot.engine.missions import MissionController, MissionStatus
from bot.engine.missions.planning import TargetChange, choose_target
from bot.world.attention import (
    AttentionSnapshot,
    EconomyFacts,
    MapFacts,
    MapObservation,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness import (
    AwarenessService,
    AwarenessSnapshot,
    EnemyAwareness,
    EnemyBaseAssessment,
    EnemyBaseAwareness,
    EnemyBaseStatus,
    EnemyForceAwareness,
    EnemyForceCluster,
    EnemyLocationKnowledge,
    RelativeStrength,
    ThreatAssessment,
)
from tests.fakes import FakeCommands, FakeLogger

HOME = Point2((10, 10))
WEST = Point2((20, 80))
EAST = Point2((100, 80))
NATURAL = Point2((80, 80))

Reading = BansheeHarassAssessment | ReaperHarassAssessment


# --- the enemy model, stated directly ----------------------------------------


def enemy_base(
    key: str,
    position: Point2,
    *,
    status: EnemyBaseStatus = EnemyBaseStatus.CONFIRMED,
    economic_value: float = 1.0,
    workers: int = 16,
    air_defense: float = 0.0,
    ground_defense: float = 0.0,
    confidence: float = 1.0,
) -> EnemyBaseAssessment:
    """A base as Awareness reports it; both defense readings are as fresh as
    the last look at the slot."""

    return EnemyBaseAssessment(
        key=key,
        position=position,
        status=status,
        economic_value=economic_value,
        worker_count_estimate=workers,
        workers_counted_at=90.0,
        air_defense=air_defense,
        air_defense_confidence=confidence,
        ground_defense=ground_defense,
        ground_defense_confidence=confidence,
        last_confirmed_at=90.0,
        last_checked_at=90.0,
        confidence=confidence,
        is_stale=confidence <= 0.0,
    )


def force(
    cluster_id: int,
    center: Point2,
    *,
    anti_air: float = 0.0,
    anti_ground: float = 0.0,
    confidence: float = 1.0,
    uncertainty: float = 0.0,
    radius: float = 2.0,
) -> EnemyForceCluster:
    return EnemyForceCluster(
        cluster_id=cluster_id,
        center=center,
        radius=radius,
        position_uncertainty=uncertainty,
        combat_strength=max(anti_air, anti_ground),
        anti_air_strength=anti_air,
        anti_ground_strength=anti_ground,
        unit_count=1,
        visible_unit_count=1,
        unit_tags=(cluster_id,),
        last_observed_at=90.0,
        confidence=confidence,
    )


def natural(*, observed_at: float | None, now: float = 100.0) -> EnemyLocationKnowledge:
    age = None if observed_at is None else now - observed_at
    return EnemyLocationKnowledge(
        key="enemy_natural",
        position=NATURAL,
        last_observed_at=observed_at,
        age=age,
        confidence=0.0 if age is None else max(0.0, 1.0 - age / 90.0),
        stale_after=90.0,
        is_stale=age is None or age >= 90.0,
    )


def enemy_model(
    *,
    now: float = 100.0,
    bases: tuple[EnemyBaseAssessment, ...] = (),
    forces: tuple[EnemyForceCluster, ...] = (),
    locations: tuple[EnemyLocationKnowledge, ...] = (),
) -> AwarenessSnapshot:
    clusters = tuple(sorted(forces, key=lambda cluster: -cluster.combat_strength))
    return AwarenessSnapshot(
        enemy=EnemyAwareness(
            sightings=(),
            locations=locations,
            bases=EnemyBaseAwareness(bases),
            forces=EnemyForceAwareness(
                clusters=clusters, main=clusters[0] if clusters else None
            ),
        ),
        relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
        threat=ThreatAssessment(0, 0, 0),
        updated_at=now,
    )


# --- our side -----------------------------------------------------------------


def own_unit(
    tag: int, unit_type: UnitTypeId, *, flying: bool = False, worker: bool = False
) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=unit_type,
        position=HOME,
        health_percentage=1.0,
        is_flying=flying,
        is_worker=worker,
        can_attack_air=False,
        can_attack_ground=True,
    )


def attention(
    now: float = 100.0,
    *,
    enemy_units: tuple[UnitSnapshot, ...] = (),
    enemy_structures: tuple[UnitSnapshot, ...] = (),
    map_facts: MapFacts | None = None,
) -> AttentionSnapshot:
    """Sixteen workers, one Banshee and one idle Reaper, on a Banshee opening."""

    return AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=500,
            vespene=200,
            supply_used=20.0,
            supply_cap=100.0,
            own_units=(
                *(own_unit(tag, UnitTypeId.SCV, worker=True) for tag in range(1, 17)),
                own_unit(500, UnitTypeId.BANSHEE, flying=True),
                own_unit(600, UnitTypeId.REAPER),
            ),
            enemy_units=enemy_units,
            enemy_structures=enemy_structures,
            map=map_facts
            or MapFacts(
                center=Point2((60, 50)),
                own_start=HOME,
                enemy_starts=(Point2((100, 90)),),
            ),
            economy=EconomyFacts(opening_name="BansheeCloak"),
        )
    )


# --- reading helpers ------------------------------------------------------------


def banshee_reading(world: AwarenessSnapshot) -> BansheeHarassAssessment:
    return BansheeHarassAssessor().assess(attention(world.updated_at), world)


def reaper_reading(world: AwarenessSnapshot) -> ReaperHarassAssessment:
    return ReaperHarassAssessor().assess(attention(world.updated_at), world)


def both_readings(world: AwarenessSnapshot) -> tuple[Reading, ...]:
    return (banshee_reading(world), reaper_reading(world))


def banshee_target(world: AwarenessSnapshot, key: str) -> BansheeTargetAssessment:
    return next(item for item in banshee_reading(world).targets if item.key == key)


def reaper_target(world: AwarenessSnapshot, key: str) -> ReaperTargetAssessment:
    return next(item for item in reaper_reading(world).targets if item.key == key)


def keys(
    targets: Sequence[BansheeTargetAssessment | ReaperTargetAssessment],
) -> list[str]:
    return [target.key for target in targets]


def preferred_key(reading: Reading) -> str | None:
    preferred = reading.preferred_target
    return None if preferred is None else preferred.key


def target_decisions(logger: FakeLogger) -> list[dict[str, Any]]:
    return [
        event["data"]
        for event in logger.events
        if event["name"] == "behavior.target_selection"
    ]


# --- ranking ------------------------------------------------------------------


class OneBaseTwoReadingsTests(unittest.TestCase):
    """The same Awareness, interpreted for two different units."""

    @staticmethod
    def contested() -> AwarenessSnapshot:
        """A rich third held by Roaches, and a main held by anti-air."""

        return enemy_model(
            bases=(
                enemy_base(
                    "expansion:3",
                    WEST,
                    economic_value=0.85,
                    workers=12,
                    ground_defense=0.75,
                    confidence=0.9,
                ),
                enemy_base("expansion:0", EAST, air_defense=0.75, ground_defense=0.25),
            ),
            forces=(force(1, Point2((22, 80)), anti_ground=6.0, confidence=0.9),),
        )

    def test_a_third_without_anti_air_suits_the_banshee_and_not_the_reaper(self):
        world = self.contested()

        banshee = banshee_target(world, "expansion:3")
        reaper = reaper_target(world, "expansion:3")

        self.assertTrue(banshee.viable)
        self.assertGreater(banshee.score, 0.6)
        self.assertFalse(reaper.viable)
        self.assertLess(reaper.score, 0.0)

    def test_each_raid_ranks_the_same_bases_its_own_way(self):
        world = self.contested()

        banshee = banshee_reading(world)
        reaper = reaper_reading(world)

        self.assertEqual(keys(banshee.targets), ["expansion:3", "expansion:0"])
        self.assertEqual(preferred_key(banshee), "expansion:3")
        self.assertEqual(keys(reaper.targets), ["expansion:0", "expansion:3"])
        self.assertEqual(preferred_key(reaper), "expansion:0")

    def test_ground_only_defense_barely_moves_a_banshee_score(self):
        world = enemy_model(
            bases=(
                enemy_base("expansion:3", WEST, ground_defense=1.0),
                enemy_base("expansion:5", EAST),
            )
        )

        held = banshee_target(world, "expansion:3")
        open_line = banshee_target(world, "expansion:5")

        self.assertTrue(held.viable)
        self.assertAlmostEqual(
            open_line.score - held.score,
            BansheeTargetHeuristics().ground_defense_weight,
        )
        self.assertFalse(reaper_target(world, "expansion:3").viable)

    def test_every_confirmed_expansion_is_a_candidate_and_nothing_else(self):
        world = enemy_model(
            bases=(
                enemy_base("expansion:7", WEST),
                enemy_base("expansion:12", EAST),
                enemy_base(
                    "expansion:4",
                    Point2((60, 20)),
                    status=EnemyBaseStatus.EMPTY,
                    economic_value=0.0,
                    workers=0,
                ),
                enemy_base(
                    "expansion:9",
                    Point2((60, 95)),
                    status=EnemyBaseStatus.UNKNOWN,
                    economic_value=0.0,
                    workers=0,
                ),
            ),
            locations=(natural(observed_at=95.0),),
        )

        for reading in both_readings(world):
            with self.subTest(reading=type(reading).__name__):
                self.assertEqual(
                    sorted(keys(reading.targets)), ["expansion:12", "expansion:7"]
                )


class UncertaintyTests(unittest.TestCase):
    def test_no_anti_air_seen_just_now_outranks_no_anti_air_seen_long_ago(self):
        world = enemy_model(
            bases=(
                enemy_base("expansion:3", WEST, confidence=0.05),
                enemy_base("expansion:5", EAST, confidence=1.0),
            )
        )

        stale = banshee_target(world, "expansion:3")

        self.assertEqual(
            keys(banshee_reading(world).targets), ["expansion:5", "expansion:3"]
        )
        self.assertEqual(banshee_target(world, "expansion:5").air_defense_risk, 0.0)
        # air_defense 0 at confidence 0.05 does not read as "no anti-air"...
        self.assertAlmostEqual(
            stale.air_defense_risk,
            0.95 * BansheeTargetHeuristics().assumed_air_defense,
        )
        # ...but not as anti-air either: the base stays a viable target.
        self.assertTrue(stale.viable)

    def test_anti_air_seen_long_ago_is_not_forgotten(self):
        world = enemy_model(
            bases=(enemy_base("expansion:3", WEST, air_defense=0.5, confidence=0.0),)
        )

        stale = banshee_target(world, "expansion:3")

        self.assertAlmostEqual(stale.air_defense_risk, 0.5)
        self.assertFalse(stale.viable)

    def test_the_reaper_pays_less_than_the_banshee_for_stale_information(self):
        fresh = enemy_model(bases=(enemy_base("expansion:3", WEST, confidence=1.0),))
        stale = enemy_model(bases=(enemy_base("expansion:3", WEST, confidence=0.0),))

        banshee_cost = (
            banshee_target(fresh, "expansion:3").score
            - banshee_target(stale, "expansion:3").score
        )
        reaper_cost = (
            reaper_target(fresh, "expansion:3").score
            - reaper_target(stale, "expansion:3").score
        )

        self.assertGreater(reaper_cost, 0.0)
        self.assertLess(reaper_cost, banshee_cost)


class ArmyRiskTests(unittest.TestCase):
    def test_a_base_near_the_enemy_army_ranks_below_an_equal_one_across_the_map(self):
        world = enemy_model(
            bases=(enemy_base("expansion:3", WEST), enemy_base("expansion:5", EAST)),
            forces=(
                force(1, Point2((30, 80)), anti_air=8.0, anti_ground=10.0, radius=3.0),
            ),
        )

        for reading in both_readings(world):
            with self.subTest(reading=type(reading).__name__):
                self.assertEqual(keys(reading.targets), ["expansion:5", "expansion:3"])
                self.assertEqual(preferred_key(reading), "expansion:5")

    def test_a_split_army_is_read_cluster_by_cluster(self):
        # The main force only shoots ground and sits on the west base; a
        # smaller detachment that only shoots air guards the east one.
        world = enemy_model(
            bases=(enemy_base("expansion:3", WEST), enemy_base("expansion:5", EAST)),
            forces=(
                force(1, Point2((25, 80)), anti_ground=12.0),
                force(2, Point2((95, 80)), anti_air=5.0),
            ),
        )

        self.assertEqual(getattr(world.enemy.main_force, "cluster_id", None), 1)
        self.assertEqual(preferred_key(banshee_reading(world)), "expansion:3")
        self.assertEqual(preferred_key(reaper_reading(world)), "expansion:5")

    def test_a_stale_cluster_weighs_less_than_a_fresh_one_in_the_same_place(self):
        base = enemy_base("expansion:3", WEST)
        fresh = enemy_model(
            bases=(base,), forces=(force(1, Point2((40, 80)), anti_air=6.0),)
        )
        stale = enemy_model(
            bases=(base,),
            forces=(
                force(
                    1, Point2((40, 80)), anti_air=6.0, confidence=0.2, uncertainty=12.0
                ),
            ),
        )

        fresh_risk = banshee_target(fresh, "expansion:3").army_risk
        stale_risk = banshee_target(stale, "expansion:3").army_risk

        self.assertGreater(stale_risk, 0.0)
        self.assertLess(stale_risk, fresh_risk)

    def test_a_cluster_that_may_have_moved_reaches_further(self):
        base = enemy_base("expansion:3", WEST)
        seen_now = enemy_model(
            bases=(base,), forces=(force(1, Point2((75, 80)), anti_air=6.0),)
        )
        seen_a_while_ago = enemy_model(
            bases=(base,),
            forces=(
                force(
                    1, Point2((75, 80)), anti_air=6.0, confidence=0.2, uncertainty=15.0
                ),
            ),
        )

        self.assertEqual(banshee_target(seen_now, "expansion:3").army_risk, 0.0)
        self.assertGreater(
            banshee_target(seen_a_while_ago, "expansion:3").army_risk, 0.0
        )


class FallbackTests(unittest.TestCase):
    def test_an_observed_natural_stands_in_while_no_base_is_confirmed(self):
        world = enemy_model(locations=(natural(observed_at=90.0),))

        for reading in both_readings(world):
            with self.subTest(reading=type(reading).__name__):
                (fallback,) = reading.targets
                self.assertEqual(fallback.key, "enemy_natural")
                self.assertTrue(fallback.is_fallback)
                self.assertTrue(fallback.viable)

    def test_a_natural_nobody_has_observed_is_no_target(self):
        world = enemy_model(locations=(natural(observed_at=None),))

        for reading in both_readings(world):
            with self.subTest(reading=type(reading).__name__):
                self.assertEqual(reading.targets, ())

    def test_a_confirmed_base_replaces_the_fallback(self):
        world = enemy_model(
            bases=(enemy_base("expansion:5", EAST),),
            locations=(natural(observed_at=90.0),),
        )

        for reading in both_readings(world):
            with self.subTest(reading=type(reading).__name__):
                self.assertEqual(keys(reading.targets), ["expansion:5"])


# --- choosing and holding a target -------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    key: str
    score: float


class ChooseTargetTests(unittest.TestCase):
    MARGIN = 0.15

    def test_a_held_target_survives_a_slightly_better_candidate(self):
        held, rival = Candidate("a", 0.70), Candidate("b", 0.73)

        choice = choose_target((rival, held), current_key="a", margin=self.MARGIN)

        self.assertEqual((choice.target, choice.change), (held, TargetChange.KEPT))

    def test_a_clearly_better_candidate_takes_over(self):
        held, rival = Candidate("a", 0.42), Candidate("b", 0.86)

        choice = choose_target((held, rival), current_key="a", margin=self.MARGIN)

        self.assertEqual(
            (choice.target, choice.change, choice.previous_key),
            (rival, TargetChange.RETARGETED, "a"),
        )

    def test_a_held_target_no_longer_offered_is_replaced_without_a_margin(self):
        rival = Candidate("b", 0.10)

        choice = choose_target((rival,), current_key="a", margin=self.MARGIN)

        self.assertEqual((choice.target, choice.change), (rival, TargetChange.REPLACED))

    def test_selecting_from_nothing_and_losing_to_nothing(self):
        best = Candidate("b", 0.5)
        nothing: tuple[Candidate, ...] = ()

        first = choose_target(
            (Candidate("a", 0.2), best), current_key=None, margin=self.MARGIN
        )
        lost = choose_target(nothing, current_key="a", margin=self.MARGIN)
        idle = choose_target(nothing, current_key=None, margin=self.MARGIN)

        self.assertEqual((first.target, first.change), (best, TargetChange.SELECTED))
        self.assertEqual((lost.target, lost.change), (None, TargetChange.LOST))
        self.assertEqual((idle.target, idle.change), (None, TargetChange.NONE))


def west_richer(now: float) -> AwarenessSnapshot:
    return enemy_model(
        now=now,
        bases=(
            enemy_base("expansion:3", WEST, economic_value=0.85, workers=12),
            enemy_base("expansion:5", EAST, economic_value=0.7, workers=8),
        ),
    )


def east_slightly_richer(now: float) -> AwarenessSnapshot:
    return enemy_model(
        now=now,
        bases=(
            enemy_base("expansion:3", WEST, economic_value=0.85, workers=12),
            enemy_base("expansion:5", EAST, economic_value=0.95, workers=14),
        ),
    )


def spore_in_the_west(now: float) -> AwarenessSnapshot:
    """An anti-air structure went up in the west; the east line filled out."""

    return enemy_model(
        now=now,
        bases=(
            enemy_base(
                "expansion:3", WEST, economic_value=0.85, workers=12, air_defense=0.25
            ),
            enemy_base("expansion:5", EAST),
        ),
    )


def queens_in_the_west(now: float) -> AwarenessSnapshot:
    """Two Queens now hold the west base; the east line is as before."""

    return enemy_model(
        now=now,
        bases=(
            enemy_base(
                "expansion:3", WEST, economic_value=0.85, workers=12, ground_defense=0.5
            ),
            enemy_base("expansion:5", EAST, economic_value=0.95, workers=14),
        ),
    )


Timeline = tuple[tuple[float, Callable[[float], AwarenessSnapshot]], ...]


class BansheeRetargetingTests(unittest.IsolatedAsyncioTestCase):
    TIMELINE: Timeline = (
        (100.0, west_richer),
        (108.0, east_slightly_richer),
        (116.0, spore_in_the_west),
    )

    def test_a_slightly_better_base_does_not_pull_the_raid_off_its_target(self):
        logger = FakeLogger()
        planner = BansheeHarassPlanner(logger=logger)

        proposals = [
            planner.propose(attention(now), world(now))[0]
            for now, world in self.TIMELINE
        ]

        self.assertEqual(
            [proposal.target_key for proposal in proposals],
            ["expansion:3", "expansion:3", "expansion:5"],
        )
        self.assertEqual(
            {proposal.deduplication_key for proposal in proposals},
            {"air_harass:banshee_harass"},
        )
        decisions = target_decisions(logger)
        # The 108 s decision kept its target inside the 30 s heartbeat.
        self.assertEqual(
            [decision["change"] for decision in decisions], ["SELECTED", "RETARGETED"]
        )
        self.assertEqual(
            (decisions[-1]["previous"], decisions[-1]["selected"]),
            ("expansion:3", "expansion:5"),
        )
        self.assertEqual(
            decisions[-1]["candidates"],
            [
                "expansion:5 score=1.00 value=1.00 aa=0.00 army_risk=0.00"
                " confidence=1.00",
                "expansion:3 score=0.56 value=0.81 aa=0.25 army_risk=0.00"
                " confidence=1.00",
            ],
        )

    def test_a_first_launch_waits_for_a_viable_target_but_a_live_raid_stays_declared(
        self,
    ):
        planner = BansheeHarassPlanner()

        def west(now: float, air_defense: float) -> AwarenessSnapshot:
            return enemy_model(
                now=now,
                bases=(enemy_base("expansion:3", WEST, air_defense=air_defense),),
            )

        self.assertEqual(planner.propose(attention(100.0), west(100.0, 0.75)), ())
        (launched,) = planner.propose(attention(101.0), west(101.0, 0.0))
        (still_live,) = planner.propose(attention(109.0), west(109.0, 0.75))

        self.assertEqual(
            (launched.target_key, launched.reason),
            ("expansion:3", "best_ranked_banshee_target"),
        )
        self.assertEqual(
            (still_live.target_key, still_live.reason),
            ("expansion:3", "raid_live_without_a_viable_target"),
        )

    def test_losing_the_only_target_is_logged_once(self):
        logger = FakeLogger()
        planner = BansheeHarassPlanner(logger=logger)
        planner.propose(attention(100.0), west_richer(100.0))

        self.assertEqual(planner.propose(attention(108.0), enemy_model(now=108.0)), ())
        self.assertEqual(planner.propose(attention(109.0), enemy_model(now=109.0)), ())

        decisions = target_decisions(logger)
        self.assertEqual(
            [decision["change"] for decision in decisions], ["SELECTED", "LOST"]
        )
        self.assertEqual(
            (decisions[-1]["previous"], decisions[-1]["selected"]),
            ("expansion:3", None),
        )

    async def test_a_retarget_moves_the_live_raid_without_replacing_it(self):
        logger = FakeLogger()
        controller = MissionController(
            logger=logger, executor_factories=build_executor_factories()
        )
        commands = FakeCommands()
        planner = BansheeHarassPlanner()

        readings = ((100.0, west_richer(100.0)), (108.0, spore_in_the_west(108.0)))
        for now, world in readings:
            current = attention(now)
            await controller.tick(
                attention=current,
                awareness=world,
                proposals=planner.propose(current, world),
                commands=commands,
            )

        (raid,) = controller.board.live()
        started = [
            event for event in logger.events if event["name"] == "mission_started"
        ]
        self.assertEqual(
            [event["data"]["mission_id"] for event in started], [raid.mission_id]
        )
        self.assertEqual(raid.status, MissionStatus.ACTIVE)
        self.assertEqual(
            (raid.proposal.target_key, raid.proposal.target), ("expansion:5", EAST)
        )
        self.assertIn(
            "standing_mission_updated", [event["name"] for event in logger.events]
        )
        # The same executor was refreshed with the new target: it now flies east.
        self.assertEqual(
            [
                command[3]
                for command in commands.commands
                if command[0] == "attack_move"
            ],
            [WEST, EAST],
        )


class ReaperRetargetingTests(unittest.TestCase):
    def test_the_next_raid_holds_its_base_unless_another_is_clearly_better(self):
        logger = FakeLogger()
        planner = ReaperHarassPlanner(logger=logger)
        timeline: Timeline = (
            (100.0, west_richer),
            (145.0, east_slightly_richer),
            (190.0, queens_in_the_west),
        )

        proposals = [
            planner.propose(attention(now), world(now))[0] for now, world in timeline
        ]

        self.assertEqual(
            [proposal.deduplication_key for proposal in proposals],
            ["harass:expansion:3", "harass:expansion:3", "harass:expansion:5"],
        )
        self.assertEqual(
            [decision["change"] for decision in target_decisions(logger)],
            ["SELECTED", "KEPT", "RETARGETED"],
        )


# --- through the real Awareness ---------------------------------------------------


class EndToEndTests(unittest.TestCase):
    def test_both_raids_target_the_expansion_awareness_confirmed(self):
        third = Point2((30, 90))
        world_map = MapFacts(
            center=Point2((60, 50)),
            own_start=HOME,
            enemy_starts=(Point2((100, 90)),),
            observations=(MapObservation("enemy_natural", NATURAL, True),),
            expansions=(
                MapObservation("expansion:0", NATURAL, True),
                MapObservation("expansion:1", third, True),
                MapObservation("expansion:2", HOME, True),
            ),
        )
        hatchery = UnitSnapshot(
            tag=700,
            unit_type=UnitTypeId.HATCHERY,
            position=third,
            health_percentage=1.0,
            is_flying=False,
            is_worker=False,
            can_attack_air=False,
            can_attack_ground=False,
            is_structure=True,
        )
        drones = tuple(
            UnitSnapshot(
                tag=800 + index,
                unit_type=UnitTypeId.DRONE,
                position=Point2((33, 90)),
                health_percentage=1.0,
                is_flying=False,
                is_worker=True,
                can_attack_air=False,
                can_attack_ground=True,
                supply_cost=1.0,
            )
            for index in range(8)
        )
        current = attention(
            enemy_units=drones, enemy_structures=(hatchery,), map_facts=world_map
        )
        world = AwarenessService().update(current)

        self.assertEqual(
            [base.key for base in world.enemy.bases.confirmed], ["expansion:1"]
        )
        planners: tuple[BansheeHarassPlanner | ReaperHarassPlanner, ...] = (
            BansheeHarassPlanner(),
            ReaperHarassPlanner(),
        )
        for planner in planners:
            with self.subTest(planner=planner.planner_id):
                (proposal,) = planner.propose(current, world)
                self.assertEqual(
                    (proposal.target_key, proposal.target), ("expansion:1", third)
                )


if __name__ == "__main__":
    unittest.main()

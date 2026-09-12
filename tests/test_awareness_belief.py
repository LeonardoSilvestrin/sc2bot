from __future__ import annotations

import math
import unittest
from itertools import pairwise

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.world.attention import (
    AttentionSnapshot,
    CountFacts,
    EconomyFacts,
    MapFacts,
    MapObservation,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness import AwarenessService
from bot.world.awareness.belief import (
    ArmyBeliefConfig,
    BeliefState,
    EconomyBeliefConfig,
    EstimateConfig,
    HysteresisState,
    LossLedger,
    LossTracker,
    RelativeBeliefConfig,
    RelativePosition,
    advance_belief,
    advance_estimate,
    advantage,
    assess_army,
    assess_economy,
)
from bot.world.awareness.belief.relative import classify
from bot.world.awareness.enemy import (
    EnemyBaseObservation,
    EnemyBaseStatus,
    EnemyRoster,
    EnemySighting,
    enemy_territory_coverage,
)

MAP = MapFacts(Point2((50, 50)), Point2((10, 10)), (Point2((90, 90)),))


def enemy_sighting(
    tag: int,
    unit_type: UnitTypeId,
    *,
    is_worker: bool = False,
    is_structure: bool = False,
    can_attack_air: bool = False,
    can_attack_ground: bool = True,
    visible_now: bool = True,
    last_seen_at: float = 0.0,
    supply_cost: float = 0.0,
) -> EnemySighting:
    return EnemySighting(
        tag=tag,
        unit_type=unit_type,
        last_position=Point2((80, 80)),
        first_seen_at=last_seen_at,
        last_seen_at=last_seen_at,
        visible_now=visible_now,
        can_attack_air=can_attack_air,
        can_attack_ground=can_attack_ground,
        is_structure=is_structure,
        is_worker=is_worker,
        supply_cost=supply_cost,
    )


def own_unit(
    tag: int, *, supply_cost: float, is_worker: bool = False
) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.SCV if is_worker else UnitTypeId.SIEGETANK,
        position=Point2((10, 10)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=is_worker,
        can_attack_air=False,
        can_attack_ground=not is_worker,
        supply_cost=supply_cost,
    )


def world_with_own_workers(*, time: float, own_workers: int) -> WorldFacts:
    return WorldFacts(
        iteration=int(time),
        time=time,
        minerals=0,
        vespene=0,
        supply_used=0,
        supply_cap=0,
        own_units=(),
        enemy_units=(),
        map=MAP,
        economy=EconomyFacts(
            workers=CountFacts(existing=own_workers, ready=own_workers)
        ),
    )


def base_observation(
    index: int, status: EnemyBaseStatus, *, checked_at: float
) -> EnemyBaseObservation:
    return EnemyBaseObservation(
        key=f"expansion:{index}",
        position=Point2((80 + 10 * index, 80)),
        status=status,
        last_confirmed_at=checked_at if status is EnemyBaseStatus.CONFIRMED else None,
        last_checked_at=checked_at,
        confidence=1.0,
        stale_after=120.0,
        is_stale=False,
    )


class EstimateTests(unittest.TestCase):
    config = EstimateConfig()

    def estimate(self, **kwargs):
        return advance_estimate(None, now=0.0, config=self.config, **kwargs)

    def test_an_unscouted_enemy_is_assumed_our_size_and_reads_even(self):
        estimate = self.estimate(known=0.0, reading=0.0, prior=40.0, information=0.0)

        self.assertAlmostEqual(estimate.mean, 40.0)
        self.assertAlmostEqual(advantage(40.0, estimate, self.config), 0.5, delta=0.02)

    def test_nothing_against_nothing_is_even(self):
        estimate = self.estimate(known=0.0, reading=0.0, prior=0.0, information=0.0)

        self.assertEqual(advantage(0.0, estimate, self.config), 0.5)

    def test_one_unit_against_one_unit_says_nothing(self):
        estimate = self.estimate(known=1.0, reading=1.0, prior=1.0, information=0.0)

        self.assertAlmostEqual(advantage(1.0, estimate, self.config), 0.5, delta=0.05)

    def test_seeing_more_than_we_have_is_decisive_however_little_is_scouted(self):
        estimate = self.estimate(known=72.0, reading=72.0, prior=50.0, information=0.0)

        self.assertLessEqual(
            advantage(50.0, estimate, self.config),
            RelativeBeliefConfig().decisive_behind,
        )

    def test_the_belief_follows_a_growing_prior_without_lagging_behind_it(self):
        # The enemy is watched to be half our size while both armies grow:
        # the belief must keep that proportion, not trail the old numbers.
        estimate = None
        for tick in range(301):
            prior = 10.0 + 0.5 * tick
            estimate = advance_estimate(
                estimate,
                now=float(tick),
                known=0.5 * prior,
                reading=0.5 * prior,
                prior=prior,
                information=0.5,
                config=self.config,
            )

        self.assertAlmostEqual(estimate.mean, 0.75 * prior, delta=0.02 * prior)

    def test_finding_units_that_were_assumed_does_not_count_them_twice(self):
        assumed = self.estimate(known=0.0, reading=0.0, prior=30.0, information=0.0)
        found = advance_estimate(
            assumed,
            now=1.0,
            known=25.0,
            reading=25.0,
            prior=30.0,
            information=0.0,
            config=self.config,
        )

        self.assertAlmostEqual(found.mean, 30.0)

    def test_a_good_reading_is_remembered_for_a_while_then_forgotten(self):
        def step(previous, now, information):
            return advance_estimate(
                previous,
                now=now,
                known=10.0,
                reading=10.0,
                prior=40.0,
                information=information,
                config=self.config,
            )

        estimate = None
        for tick in range(21):
            estimate = step(estimate, float(tick), 0.85)
        self.assertLess(estimate.mean, 18.0)

        remembered = step(estimate, 50.0, 0.0)
        self.assertLess(remembered.mean, 25.0)

        forgotten = step(remembered, 400.0, 0.0)
        self.assertGreater(forgotten.mean, 38.0)

    def test_weak_glimpses_never_add_up_to_having_seen_everything(self):
        estimate = None
        for tick in range(601):
            estimate = advance_estimate(
                estimate,
                now=float(tick),
                known=0.0,
                reading=0.0,
                prior=40.0,
                information=0.1,
                config=self.config,
            )

        self.assertGreaterEqual(estimate.mean, 36.0 - 1e-6)

    def test_advantage_grows_smoothly_with_our_own_number(self):
        estimate = self.estimate(known=10.0, reading=10.0, prior=30.0, information=0.3)
        readings = [
            advantage(float(own), estimate, self.config) for own in range(0, 80, 5)
        ]

        self.assertTrue(all(b >= a for a, b in pairwise(readings)))
        self.assertLess(readings[0], 0.5)
        self.assertGreater(readings[-1], 0.5)


class RosterAndLossTests(unittest.TestCase):
    def test_roster_keeps_units_ares_forgot_until_the_game_reports_them_dead(self):
        roster = EnemyRoster()
        marine = enemy_sighting(
            7, UnitTypeId.MARINE, supply_cost=1.0, last_seen_at=10.0
        )
        bunker = enemy_sighting(8, UnitTypeId.BUNKER, is_structure=True)

        self.assertEqual(
            roster.update((marine, bunker), dead_tags=frozenset()).alive, (marine,)
        )
        self.assertEqual(roster.update((), dead_tags=frozenset()).alive, (marine,))

        died = roster.update((), dead_tags=frozenset({7}))
        self.assertEqual((died.alive, died.died), ((), (marine,)))

        # Dead tags are reported on two observations and Ares may echo the
        # unit once more: still a single loss, and never alive again.
        again = roster.update((marine,), dead_tags=frozenset({7}))
        self.assertEqual((again.alive, again.died), ((), ()))

    def test_losses_count_only_reported_deaths_and_fade_as_both_sides_rebuild(self):
        tracker = LossTracker(recovery_time_constant=100.0)

        def world(time, units, dead=()):
            return WorldFacts(
                iteration=int(time),
                time=time,
                minerals=0,
                vespene=0,
                supply_used=0,
                supply_cap=0,
                own_units=units,
                enemy_units=(),
                map=MAP,
                dead_unit_tags=frozenset(dead),
            )

        tank = own_unit(1, supply_cost=3.0)
        scv = own_unit(2, supply_cost=1.0, is_worker=True)
        marine = own_unit(3, supply_cost=1.0)
        tracker.update(world(0.0, (tank, scv, marine)), enemy_died=())

        ledger = tracker.update(
            world(1.0, (marine,), dead={1, 2}),
            enemy_died=(enemy_sighting(9, UnitTypeId.ROACH, supply_cost=2.0),),
        )
        self.assertEqual(
            (ledger.own_supply, ledger.own_workers, ledger.enemy_supply),
            (4.0, 1.0, 2.0),
        )

        # The marine loads into a bunker: gone from view, not dead.
        hidden = tracker.update(world(2.0, ()), enemy_died=())
        self.assertAlmostEqual(hidden.own_supply, 4.0 * math.exp(-1.0 / 100.0))

        faded = tracker.update(world(102.0, ()), enemy_died=())
        self.assertAlmostEqual(faded.own_supply, hidden.own_supply * math.exp(-1.0))


class RelativePositionTests(unittest.TestCase):
    config = RelativeBeliefConfig(persist_seconds=8.0)

    def read(self, advantage_value, stable, *, informed=True):
        position, _ = classify(
            advantage=advantage_value,
            informed=informed,
            state=HysteresisState(stable=stable),
            config=self.config,
        )
        return position

    def test_an_axis_without_evidence_stays_unknown(self):
        self.assertIs(
            self.read(0.95, RelativePosition.UNKNOWN, informed=False),
            RelativePosition.UNKNOWN,
        )

    def test_entering_a_position_takes_more_than_staying_in_it(self):
        self.assertIs(self.read(0.70, RelativePosition.EVEN), RelativePosition.EVEN)
        self.assertIs(self.read(0.65, RelativePosition.AHEAD), RelativePosition.AHEAD)
        self.assertIs(self.read(0.55, RelativePosition.AHEAD), RelativePosition.EVEN)
        self.assertIs(self.read(0.35, RelativePosition.EVEN), RelativePosition.EVEN)
        self.assertIs(self.read(0.35, RelativePosition.BEHIND), RelativePosition.BEHIND)

    def step(self, state, now, advantage_value, *, informed=True):
        return advance_belief(
            now=now,
            advantage=advantage_value,
            informed=informed,
            confidence=0.5,
            reason="because",
            state=state,
            config=self.config,
        )

    def test_a_new_position_must_hold_before_it_is_believed(self):
        state = HysteresisState(stable=RelativePosition.EVEN)
        for tick in range(8):
            _, state = self.step(state, float(tick), 0.80)
        self.assertIs(state.stable, RelativePosition.EVEN)

        _, state = self.step(state, 8.0, 0.80)
        self.assertIs(state.stable, RelativePosition.AHEAD)

    def test_a_pending_position_survives_dips_that_stay_above_its_exit(self):
        state = HysteresisState(stable=RelativePosition.EVEN)
        for tick in range(9):
            _, state = self.step(state, float(tick), 0.80 if tick % 2 == 0 else 0.65)

        self.assertIs(state.stable, RelativePosition.AHEAD)

    def test_a_decisive_deficit_is_believed_at_once(self):
        assessment, state = self.step(
            HysteresisState(stable=RelativePosition.AHEAD), 0.0, 0.05
        )

        self.assertIs(state.stable, RelativePosition.BEHIND)
        self.assertEqual(assessment.reason, "because")

    def test_lack_of_evidence_never_replaces_a_believed_position(self):
        assessment, state = self.step(
            HysteresisState(stable=RelativePosition.BEHIND), 0.0, 0.9, informed=False
        )

        self.assertIs(assessment.raw_state, RelativePosition.UNKNOWN)
        self.assertIs(state.stable, RelativePosition.BEHIND)


class EconomyBeliefTests(unittest.TestCase):
    def assess(self, world, **kwargs):
        arguments = dict(
            sightings=(),
            roster=(),
            base_observations=(),
            losses=LossLedger(),
            coverage=0.0,
            visibility=0.0,
            scouted=True,
            state=BeliefState(),
            config=EconomyBeliefConfig(),
        )
        arguments.update(kwargs)
        return assess_economy(world=world, **arguments)

    def test_more_enemy_workers_seen_than_we_have_is_behind_at_once(self):
        world = world_with_own_workers(time=100.0, own_workers=45)
        workers = tuple(
            enemy_sighting(tag, UnitTypeId.SCV, is_worker=True, last_seen_at=100.0)
            for tag in range(1, 54)
        )

        belief, _ = self.assess(world, sightings=workers, roster=workers)

        self.assertEqual(belief.enemy.workers.observed, 53)
        self.assertIs(belief.relative.stable_state, RelativePosition.BEHIND)

    def test_an_unscouted_enemy_economy_is_assumed_our_size(self):
        world = world_with_own_workers(time=100.0, own_workers=45)

        belief, _ = self.assess(world)

        self.assertEqual(belief.enemy.workers.estimated, 45)
        self.assertEqual(belief.enemy.bases.confidence, 0.0)
        self.assertIs(belief.relative.raw_state, RelativePosition.EVEN)

    def test_confirmed_bases_project_workers(self):
        world = world_with_own_workers(time=50.0, own_workers=10)
        observations = tuple(
            base_observation(index, EnemyBaseStatus.CONFIRMED, checked_at=50.0)
            for index in range(2)
        )

        belief, _ = self.assess(
            world,
            base_observations=observations,
            visibility=enemy_territory_coverage(observations),
        )

        self.assertEqual(belief.enemy.bases.confirmed, 2)
        self.assertEqual(belief.enemy.workers.estimated, 32)  # 2 * 16 assumed/base
        self.assertIs(belief.relative.raw_state, RelativePosition.BEHIND)

    def test_empty_expansions_are_no_evidence_of_a_small_economy(self):
        world = world_with_own_workers(time=50.0, own_workers=30)
        observations = tuple(
            base_observation(index, EnemyBaseStatus.EMPTY, checked_at=50.0)
            for index in range(6)
        )

        self.assertEqual(enemy_territory_coverage(observations), 0.0)
        belief, _ = self.assess(
            world,
            base_observations=observations,
            visibility=enemy_territory_coverage(observations),
        )
        self.assertEqual(belief.enemy.workers.estimated, 30)


class ArmyBeliefTests(unittest.TestCase):
    def world(self, own_units, *, supply_used=0.0):
        return WorldFacts(
            iteration=1,
            time=100.0,
            minerals=0,
            vespene=0,
            supply_used=supply_used,
            supply_cap=0,
            own_units=own_units,
            enemy_units=(),
            map=MAP,
        )

    def assess(self, world, **kwargs):
        arguments = dict(
            sightings=(),
            roster=(),
            losses=LossLedger(),
            enemy_workers=0.0,
            visibility=0.0,
            scouted=True,
            state=BeliefState(),
            config=ArmyBeliefConfig(),
        )
        arguments.update(kwargs)
        return assess_army(world=world, **arguments)

    def test_army_comparison_uses_supply_not_unit_count(self):
        tanks = (own_unit(1, supply_cost=25.0), own_unit(2, supply_cost=25.0))
        # 20 cheap units outnumber our 2 tanks but carry far less supply.
        lings = tuple(
            enemy_sighting(
                tag, UnitTypeId.ZERGLING, last_seen_at=100.0, supply_cost=0.5
            )
            for tag in range(1, 21)
        )

        belief, _ = self.assess(
            self.world(tanks), sightings=lings, roster=lings, visibility=1.0
        )

        self.assertEqual(belief.own_supply, 50.0)
        self.assertAlmostEqual(belief.enemy.supply.known, 10.0)
        self.assertIs(belief.relative.raw_state, RelativePosition.AHEAD)

    def test_a_few_visible_units_do_not_mean_ahead_while_the_enemy_is_unwatched(self):
        tanks = (own_unit(1, supply_cost=50.0),)
        lings = tuple(
            enemy_sighting(
                tag, UnitTypeId.ZERGLING, last_seen_at=100.0, supply_cost=0.5
            )
            for tag in range(1, 3)
        )

        belief, _ = self.assess(self.world(tanks), sightings=lings, roster=lings)

        self.assertIsNot(belief.relative.raw_state, RelativePosition.AHEAD)

    def test_an_army_that_left_vision_still_counts(self):
        roaches = tuple(
            enemy_sighting(
                tag,
                UnitTypeId.ROACH,
                last_seen_at=40.0,
                visible_now=False,
                supply_cost=2.0,
            )
            for tag in range(1, 11)
        )

        # Ares no longer reports them (no sightings); only the roster does.
        belief, _ = self.assess(self.world(()), roster=roaches)

        self.assertGreater(belief.enemy.supply.known, 16.0)
        self.assertGreaterEqual(
            belief.enemy.supply.estimated, belief.enemy.supply.known
        )

    def test_not_having_seen_an_army_is_no_evidence_that_it_is_small(self):
        army = tuple(own_unit(tag, supply_cost=2.0) for tag in range(10))

        belief, _ = self.assess(
            self.world(army, supply_used=60.0), enemy_workers=30.0, visibility=1.0
        )

        # Our 60 supply minus the 30 workers believed on their side.
        self.assertAlmostEqual(belief.enemy.supply.estimated, 30.0)


def _enemy_worker_unit(tag: int, *, visible_now: bool = True) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.SCV,
        position=Point2((80, 80)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=True,
        can_attack_air=False,
        can_attack_ground=False,
        visible_now=visible_now,
    )


def _enemy_combat_unit(
    tag: int, *, supply_cost: float, visible_now: bool = True
) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=UnitTypeId.ZERGLING,
        position=Point2((80, 80)),
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=True,
        visible_now=visible_now,
        supply_cost=supply_cost,
    )


def _army_world(
    time: float,
    *,
    own_units: tuple[UnitSnapshot, ...],
    enemy_units: tuple[UnitSnapshot, ...] = (),
    workers: int = 30,
) -> AttentionSnapshot:
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(time),
            time=time,
            minerals=0,
            vespene=0,
            supply_used=float(workers + sum(unit.supply_cost for unit in own_units)),
            supply_cap=200.0,
            own_units=own_units,
            enemy_units=enemy_units,
            map=MAP,
            economy=EconomyFacts(workers=CountFacts(existing=workers, ready=workers)),
        )
    )


class AwarenessServiceChatTests(unittest.TestCase):
    def test_partial_scout_glimpse_does_not_announce_ahead(self):
        service = AwarenessService()
        own_army = UnitSnapshot(
            tag=1,
            unit_type=UnitTypeId.SIEGETANK,
            position=Point2((10, 10)),
            health_percentage=1.0,
            is_flying=False,
            is_worker=False,
            can_attack_air=False,
            can_attack_ground=True,
            supply_cost=10.0,
        )
        enemy = _enemy_combat_unit(2, supply_cost=2.0)
        expansions = tuple(
            MapObservation(
                key=f"expansion:{index}",
                position=Point2((30 + index * 20, 30)),
                visible_now=index == 0,
            )
            for index in range(6)
        )

        result = service.update(
            AttentionSnapshot(
                WorldFacts(
                    iteration=100,
                    time=100.0,
                    minerals=0,
                    vespene=0,
                    supply_used=0,
                    supply_cap=0,
                    own_units=(own_army,),
                    enemy_units=(enemy,),
                    map=MapFacts(
                        center=MAP.center,
                        own_start=MAP.own_start,
                        enemy_starts=MAP.enemy_starts,
                        expansions=expansions,
                    ),
                )
            )
        )

        # 10 vs 2 on screen, but none of the enemy's territory is watched:
        # the glimpse is no reason to believe the enemy army is small.
        self.assertLess(result.relative_strength.score, 0.5)
        self.assertIsNot(result.army.relative.raw_state, RelativePosition.AHEAD)
        self.assertIs(result.army.relative.stable_state, RelativePosition.UNKNOWN)
        self.assertEqual(result.belief_changes, ())

    def test_change_is_reported_when_stable_state_changes_and_axes_are_independent(
        self,
    ):
        service = AwarenessService()

        def tick(
            time: float,
            *,
            own_workers: int,
            enemy_units: tuple[UnitSnapshot, ...] = (),
        ):
            world = WorldFacts(
                iteration=int(time),
                time=time,
                minerals=0,
                vespene=0,
                supply_used=0,
                supply_cap=0,
                own_units=(),
                enemy_units=enemy_units,
                map=MAP,
                economy=EconomyFacts(
                    workers=CountFacts(existing=own_workers, ready=own_workers)
                ),
            )
            return service.update(AttentionSnapshot(world))

        # Nothing known yet -- both axes start and stay UNKNOWN, no change.
        first = tick(10.0, own_workers=10)
        self.assertEqual(first.belief_changes, ())
        self.assertEqual(first.economy.relative.stable_state, RelativePosition.UNKNOWN)
        self.assertEqual(first.army.relative.stable_state, RelativePosition.UNKNOWN)

        # 15 enemy workers directly observed against our 10 is hard proof --
        # ECONOMY should flip immediately; ARMY has no evidence yet.
        second = tick(
            20.0,
            own_workers=10,
            enemy_units=tuple(_enemy_worker_unit(tag) for tag in range(1, 16)),
        )
        self.assertEqual(len(second.belief_changes), 1)
        self.assertIn("ECONOMY", second.belief_changes[0])
        self.assertIn("UNKNOWN -> BEHIND", second.belief_changes[0])
        self.assertEqual(second.army.relative.stable_state, RelativePosition.UNKNOWN)

        # Unchanged world the next tick -- no new belief change.
        third = tick(
            21.0,
            own_workers=10,
            enemy_units=tuple(_enemy_worker_unit(tag) for tag in range(1, 16)),
        )
        self.assertEqual(third.belief_changes, ())
        self.assertEqual(third.economy.relative.stable_state, RelativePosition.BEHIND)

        # Workers dropping out of vision do not change the belief.
        fourth = tick(
            22.0,
            own_workers=10,
            enemy_units=tuple(
                _enemy_worker_unit(tag, visible_now=False) for tag in range(1, 16)
            ),
        )
        self.assertEqual(fourth.belief_changes, ())

        # A real enemy army against our none -- ARMY flips on its own,
        # without re-announcing ECONOMY.
        fifth = tick(
            30.0,
            own_workers=10,
            enemy_units=(
                *(_enemy_worker_unit(tag, visible_now=False) for tag in range(1, 16)),
                _enemy_combat_unit(100, supply_cost=12.0),
            ),
        )
        self.assertEqual(len(fifth.belief_changes), 1)
        self.assertIn("ARMY", fifth.belief_changes[0])
        self.assertIn("UNKNOWN -> BEHIND", fifth.belief_changes[0])

    def test_an_early_even_trade_does_not_lock_the_army_behind(self):
        # The game log that motivated the estimate: one Marine against one
        # Reaper at 150 s used to set BEHIND for good, still standing with
        # 68 supply against nothing seen for five minutes.
        service = AwarenessService()
        army_messages = []
        for tick in range(100, 481):
            own_supply = 1 if tick < 230 else min(68, 1 + (tick - 230) // 3)
            result = service.update(
                _army_world(
                    float(tick),
                    own_units=tuple(
                        own_unit(1000 + index, supply_cost=1.0)
                        for index in range(own_supply)
                    ),
                    enemy_units=(
                        (_enemy_combat_unit(50, supply_cost=1.0),)
                        if tick <= 155
                        else ()
                    ),
                )
            )
            army_messages.extend(
                message for message in result.belief_changes if "ARMY" in message
            )

        self.assertIsNot(result.army.relative.stable_state, RelativePosition.BEHIND)
        self.assertLessEqual(len(army_messages), 2)

    def test_a_unit_flickering_in_and_out_of_vision_does_not_move_the_belief(self):
        service = AwarenessService()
        own = tuple(own_unit(1000 + index, supply_cost=2.0) for index in range(10))
        states = []
        readings = []
        for tick in range(121):
            result = service.update(
                _army_world(
                    float(tick),
                    own_units=own,
                    enemy_units=(
                        _enemy_combat_unit(
                            50, supply_cost=2.0, visible_now=(tick // 3) % 2 == 0
                        ),
                    ),
                )
            )
            states.append(result.army.relative.stable_state)
            readings.append(result.army.relative.advantage)

        self.assertLessEqual(sum(1 for a, b in pairwise(states) if a is not b), 1)
        self.assertLess(max(abs(b - a) for a, b in pairwise(readings)), 0.05)


if __name__ == "__main__":
    unittest.main()

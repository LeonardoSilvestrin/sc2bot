from __future__ import annotations

import unittest

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
    EconomyBeliefConfig,
    HysteresisState,
    RelativeBeliefConfig,
    RelativePosition,
    advance_belief,
    assess_army,
    assess_economy,
)
from bot.world.awareness.enemy import (
    EnemyBaseObservation,
    EnemyBaseStatus,
    EnemySighting,
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


class EconomyBeliefTests(unittest.TestCase):
    def test_partial_observation_with_low_coverage_does_not_become_certainty(self):
        world = world_with_own_workers(time=100.0, own_workers=45)
        sightings = tuple(
            enemy_sighting(tag, UnitTypeId.SCV, is_worker=True, last_seen_at=100.0)
            for tag in range(1, 26)
        )

        belief, _ = assess_economy(
            world=world,
            sightings=sightings,
            base_observations=(),
            coverage=0.0,
            now=100.0,
            state=HysteresisState(),
            config=EconomyBeliefConfig(),
        )

        self.assertEqual(belief.enemy.workers.observed, 25)
        self.assertEqual(belief.relative.raw_state, RelativePosition.UNKNOWN)

    def test_enemy_workers_observed_over_own_total_conclude_behind_confidently(self):
        world = world_with_own_workers(time=100.0, own_workers=45)
        sightings = tuple(
            enemy_sighting(tag, UnitTypeId.SCV, is_worker=True, last_seen_at=100.0)
            for tag in range(1, 54)
        )

        belief, _ = assess_economy(
            world=world,
            sightings=sightings,
            base_observations=(),
            # Low coverage does not matter here -- this is direct proof.
            coverage=0.0,
            now=100.0,
            state=HysteresisState(),
            config=EconomyBeliefConfig(),
        )

        self.assertEqual(belief.relative.raw_state, RelativePosition.BEHIND)
        self.assertGreaterEqual(belief.relative.confidence, 0.75)

    def test_information_ages_and_loses_confidence(self):
        world = world_with_own_workers(time=1000.0, own_workers=20)
        sightings = (
            enemy_sighting(
                1, UnitTypeId.SCV, is_worker=True, last_seen_at=0.0, visible_now=False
            ),
        )

        belief, _ = assess_economy(
            world=world,
            sightings=sightings,
            base_observations=(),
            coverage=1.0,
            now=1000.0,
            state=HysteresisState(),
            config=EconomyBeliefConfig(),
        )

        self.assertEqual(belief.enemy.workers.confidence, 0.0)
        self.assertEqual(belief.relative.raw_state, RelativePosition.UNKNOWN)

    def test_confirmed_bases_are_kept_in_memory_and_project_a_worker_floor(self):
        world = world_with_own_workers(time=50.0, own_workers=10)
        base_observations = tuple(
            EnemyBaseObservation(
                key=f"expansion:{index}",
                position=Point2((80 + index, 80)),
                status=EnemyBaseStatus.CONFIRMED,
                last_confirmed_at=50.0,
                last_checked_at=50.0,
                confidence=1.0,
                stale_after=120.0,
                is_stale=False,
            )
            for index in range(2)
        )

        belief, _ = assess_economy(
            world=world,
            sightings=(),
            base_observations=base_observations,
            coverage=1.0,
            now=50.0,
            state=HysteresisState(),
            config=EconomyBeliefConfig(),
        )

        self.assertEqual(belief.enemy.bases.confirmed, 2)
        self.assertEqual(belief.enemy.workers.estimated, 32)  # 2 * 16 assumed/base
        self.assertEqual(belief.relative.raw_state, RelativePosition.BEHIND)


class ArmyBeliefTests(unittest.TestCase):
    def test_army_comparison_uses_supply_not_unit_count(self):
        own_units = (
            UnitSnapshot(
                tag=1,
                unit_type=UnitTypeId.SIEGETANK,
                position=Point2((10, 10)),
                health_percentage=1.0,
                is_flying=False,
                is_worker=False,
                can_attack_air=False,
                can_attack_ground=True,
                supply_cost=25.0,
            ),
            UnitSnapshot(
                tag=2,
                unit_type=UnitTypeId.SIEGETANK,
                position=Point2((10, 10)),
                health_percentage=1.0,
                is_flying=False,
                is_worker=False,
                can_attack_air=False,
                can_attack_ground=True,
                supply_cost=25.0,
            ),
        )
        world = WorldFacts(
            iteration=1,
            time=100.0,
            minerals=0,
            vespene=0,
            supply_used=0,
            supply_cap=0,
            own_units=own_units,
            enemy_units=(),
            map=MAP,
        )
        # 20 cheap units easily outnumber our 2 tanks, but carry far less
        # total supply -- the belief must side with supply, not the count.
        sightings = tuple(
            enemy_sighting(
                tag,
                UnitTypeId.ZERGLING,
                last_seen_at=100.0,
                supply_cost=0.5,
            )
            for tag in range(1, 21)
        )

        belief, _ = assess_army(
            world=world,
            sightings=sightings,
            coverage=1.0,
            now=100.0,
            state=HysteresisState(),
            config=ArmyBeliefConfig(),
        )

        self.assertEqual(belief.own_supply, 50.0)
        self.assertEqual(belief.enemy.supply.estimated, 10.0)
        self.assertEqual(belief.relative.raw_state, RelativePosition.AHEAD)

    def test_a_few_visible_enemy_units_do_not_automatically_mean_ahead(self):
        own_units = (
            UnitSnapshot(
                tag=1,
                unit_type=UnitTypeId.SIEGETANK,
                position=Point2((10, 10)),
                health_percentage=1.0,
                is_flying=False,
                is_worker=False,
                can_attack_air=False,
                can_attack_ground=True,
                supply_cost=50.0,
            ),
        )
        world = WorldFacts(
            iteration=1,
            time=100.0,
            minerals=0,
            vespene=0,
            supply_used=0,
            supply_cap=0,
            own_units=own_units,
            enemy_units=(),
            map=MAP,
        )
        sightings = (
            enemy_sighting(1, UnitTypeId.ZERGLING, last_seen_at=100.0, supply_cost=0.5),
            enemy_sighting(2, UnitTypeId.ZERGLING, last_seen_at=100.0, supply_cost=0.5),
        )

        belief, _ = assess_army(
            world=world,
            sightings=sightings,
            # Nothing has been scouted -- unseen production could easily
            # close this gap, so a handful of visible lings must not read
            # as us being ahead.
            coverage=0.0,
            now=100.0,
            state=HysteresisState(),
            config=ArmyBeliefConfig(),
        )

        self.assertEqual(belief.relative.raw_state, RelativePosition.UNKNOWN)


class HysteresisTests(unittest.TestCase):
    def test_small_oscillations_near_threshold_do_not_change_stable_state(self):
        config = RelativeBeliefConfig(persist_seconds=10.0)
        state = HysteresisState(stable=RelativePosition.EVEN)

        for tick, estimated in enumerate([42.0, 44.0, 42.0, 44.0, 42.0]):
            _, state = advance_belief(
                now=float(tick),
                own=50.0,
                estimated=estimated,
                observed=0.0,
                confidence=0.9,
                reason="",
                state=state,
                config=config,
            )

        self.assertEqual(state.stable, RelativePosition.EVEN)

    def test_marginal_evidence_must_persist_before_stable_state_changes(self):
        config = RelativeBeliefConfig(persist_seconds=10.0)
        state = HysteresisState(stable=RelativePosition.EVEN)

        for tick in range(10):  # now = 0..9, short of the 10s requirement
            _, state = advance_belief(
                now=float(tick),
                own=50.0,
                estimated=40.0,  # ratio 0.2: past ahead_ratio, below strong_ratio
                observed=0.0,
                confidence=0.9,
                reason="",
                state=state,
                config=config,
            )
        self.assertEqual(state.stable, RelativePosition.EVEN)

        _, state = advance_belief(
            now=10.0,
            own=50.0,
            estimated=40.0,
            observed=0.0,
            confidence=0.9,
            reason="",
            state=state,
            config=config,
        )
        self.assertEqual(state.stable, RelativePosition.AHEAD)

    def test_strong_apparent_advantage_still_requires_persistence(self):
        config = RelativeBeliefConfig(strong_ratio=0.45)
        state = HysteresisState(stable=RelativePosition.EVEN)

        assessment, state = advance_belief(
            now=0.0,
            own=50.0,
            estimated=20.0,  # ratio 0.6 >= strong_ratio
            observed=0.0,
            confidence=0.9,
            reason="",
            state=state,
            config=config,
        )

        self.assertEqual(assessment.raw_state, RelativePosition.AHEAD)
        self.assertEqual(state.stable, RelativePosition.EVEN)
        self.assertEqual(assessment.stable_state, RelativePosition.EVEN)

    def test_large_apparent_advantage_needs_more_than_barely_enough_confidence(self):
        assessment, state = advance_belief(
            now=0.0,
            own=50.0,
            estimated=5.0,
            observed=5.0,
            # This used to be enough to announce AHEAD after seeing only a
            # tiny slice of the opponent's army.
            confidence=0.40,
            reason="",
            state=HysteresisState(),
            config=RelativeBeliefConfig(),
        )

        self.assertEqual(assessment.raw_state, RelativePosition.UNKNOWN)
        self.assertEqual(state.stable, RelativePosition.UNKNOWN)

    def test_lost_vision_reduces_confidence_without_erasing_stable_belief(self):
        config = RelativeBeliefConfig(persist_seconds=8.0)
        state = HysteresisState(stable=RelativePosition.BEHIND)

        assessment, state = advance_belief(
            now=120.0,
            own=50.0,
            estimated=20.0,
            observed=0.0,
            confidence=0.0,
            reason="",
            state=state,
            config=config,
        )

        self.assertEqual(assessment.raw_state, RelativePosition.UNKNOWN)
        self.assertEqual(assessment.stable_state, RelativePosition.BEHIND)
        self.assertEqual(state.stable, RelativePosition.BEHIND)
        self.assertIsNone(state.pending)

    def test_hard_observed_evidence_flips_state_immediately(self):
        # Mirrors the spec example: own army=50, enemy observed=72.
        config = RelativeBeliefConfig()
        state = HysteresisState(stable=RelativePosition.AHEAD)

        assessment, state = advance_belief(
            now=0.0,
            own=50.0,
            estimated=72.0,
            observed=72.0,
            confidence=0.2,
            reason="enemy army sighted",
            state=state,
            config=config,
        )

        self.assertEqual(state.stable, RelativePosition.BEHIND)
        self.assertEqual(assessment.reason, "enemy army sighted")


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
                position=Point2((30 + index * 5, 30)),
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

        # Numerically 10 vs 2 looks overwhelming, but only one sixth of the
        # map has been checked. This exact shape caused the game-log flaps.
        self.assertGreater(result.relative_strength.score, 0.5)
        self.assertEqual(result.army.relative.raw_state, RelativePosition.UNKNOWN)
        self.assertEqual(result.army.relative.stable_state, RelativePosition.UNKNOWN)
        self.assertEqual(result.chat_messages, ())

    def test_chat_fires_exactly_when_stable_state_changes_and_axes_are_independent(
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

        # Nothing known yet -- both axes start and stay UNKNOWN, no chat.
        first = tick(10.0, own_workers=10)
        self.assertEqual(first.chat_messages, ())
        self.assertEqual(first.economy.relative.stable_state, RelativePosition.UNKNOWN)
        self.assertEqual(first.army.relative.stable_state, RelativePosition.UNKNOWN)

        # 15 enemy workers directly observed against our 10 is hard proof --
        # ECONOMY should flip immediately; ARMY has no evidence yet.
        second = tick(
            20.0,
            own_workers=10,
            enemy_units=tuple(_enemy_worker_unit(tag) for tag in range(1, 16)),
        )
        self.assertEqual(len(second.chat_messages), 1)
        self.assertIn("ECONOMY", second.chat_messages[0])
        self.assertIn("UNKNOWN -> BEHIND", second.chat_messages[0])
        self.assertEqual(second.army.relative.stable_state, RelativePosition.UNKNOWN)

        # Unchanged world the next tick -- no new belief change, no chat.
        third = tick(
            21.0,
            own_workers=10,
            enemy_units=tuple(_enemy_worker_unit(tag) for tag in range(1, 16)),
        )
        self.assertEqual(third.chat_messages, ())
        self.assertEqual(third.economy.relative.stable_state, RelativePosition.BEHIND)

        # A confidence-only change (workers dropping out of vision without
        # the belief itself changing direction) must stay silent too.
        fourth = tick(
            22.0,
            own_workers=10,
            enemy_units=tuple(
                _enemy_worker_unit(tag, visible_now=False) for tag in range(1, 16)
            ),
        )
        self.assertEqual(fourth.chat_messages, ())

        # Now enemy combat supply alone matches our (zero) army -- ARMY
        # should flip on its own, without re-announcing ECONOMY.
        fifth = tick(
            30.0,
            own_workers=10,
            enemy_units=(
                *(_enemy_worker_unit(tag, visible_now=False) for tag in range(1, 16)),
                _enemy_combat_unit(100, supply_cost=2.0),
            ),
        )
        self.assertEqual(len(fifth.chat_messages), 1)
        self.assertIn("ARMY", fifth.chat_messages[0])
        self.assertIn("UNKNOWN -> BEHIND", fifth.chat_messages[0])


if __name__ == "__main__":
    unittest.main()

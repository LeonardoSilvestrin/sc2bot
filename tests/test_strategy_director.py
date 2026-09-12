"""Hysteresis and the stateful director: the objective in force changes only
on a clear, lasting reason -- or at once for a critical threat."""

from __future__ import annotations

import unittest
from dataclasses import fields, replace
from typing import Any

from bot.strategy import (
    ObjectiveAssessment,
    ObjectiveState,
    StabilizeWeights,
    StrategicDirector,
    StrategicObjective,
    StrategyConfig,
    StrategyInputs,
    StrategySnapshot,
    TakeMapControlWeights,
    decision_confidence,
    select_objective,
)
from tests.test_strategy_scoring import (
    COLD_START,
    EVEN_STABLE,
    HIGH_THREAT,
    MAP_CONTROL,
    PRESSURE_READY,
    scores,
    signals,
)

CONFIG = StrategyConfig()
DWELL = CONFIG.minimum_dwell_seconds

STABILIZE = StrategicObjective.STABILIZE
RECOVER = StrategicObjective.RECOVER
BUILD_ADVANTAGE = StrategicObjective.BUILD_ADVANTAGE
TAKE_MAP_CONTROL = StrategicObjective.TAKE_MAP_CONTROL
PRESSURE = StrategicObjective.PRESSURE

MODERATE_THREAT = signals(immediate_threat=0.6, base_exposure=0.4)
# MAP_CONTROL leads BUILD_ADVANTAGE here, but by less than the switch margin.
NEAR_TIE = signals(military_edge=0.31)


def assessments(**by_name: float) -> tuple[ObjectiveAssessment, ...]:
    """Synthetic assessments: ``pressure=0.7`` scores PRESSURE 0.7, others 0."""

    return tuple(
        ObjectiveAssessment(objective, by_name.get(objective.name.lower(), 0.0), ())
        for objective in StrategicObjective
    )


def select(
    state: ObjectiveState,
    now: float,
    *,
    threat: float = 0.0,
    config: StrategyConfig = CONFIG,
    **by_name: float,
) -> ObjectiveState:
    return select_objective(
        state=state,
        assessments=assessments(**by_name),
        immediate_threat=threat,
        now=now,
        config=config,
    )


def run(
    director: StrategicDirector,
    inputs: StrategyInputs,
    start: float,
    stop: float,
) -> list[StrategySnapshot]:
    """One update per second over ``[start, stop]``."""

    return [
        director.update(inputs, float(second))
        for second in range(int(start), int(stop) + 1)
    ]


class SelectObjectiveTests(unittest.TestCase):
    """The hysteresis rule alone, on synthetic scores."""

    def setUp(self):
        self.state = ObjectiveState(objective=BUILD_ADVANTAGE, entered_at=0.0)

    def test_a_challenger_inside_the_margin_never_takes_over(self):
        config = replace(CONFIG, switch_margin=0.08, minimum_dwell_seconds=0.0)
        state = self.state
        for tick in range(100):
            # The lead flips every tick, but never by the margin.
            if tick % 2:
                state = select(
                    state, tick, config=config, build_advantage=0.5, pressure=0.55
                )
            else:
                state = select(
                    state, tick, config=config, build_advantage=0.55, pressure=0.5
                )

        self.assertIs(state, self.state)

    def test_a_challenger_at_the_margin_after_the_dwell_takes_over(self):
        config = replace(CONFIG, switch_margin=0.25)

        state = select(
            self.state, DWELL, config=config, build_advantage=0.5, pressure=0.75
        )

        self.assertEqual(
            state,
            ObjectiveState(
                objective=PRESSURE, entered_at=DWELL, previous=BUILD_ADVANTAGE
            ),
        )

    def test_the_dwell_holds_even_a_clear_winner(self):
        state = select(self.state, DWELL - 0.5, build_advantage=0.1, pressure=1.0)

        self.assertIs(state, self.state)

    def test_a_critical_threat_lets_stabilize_skip_the_dwell(self):
        state = select(self.state, 1.0, threat=0.85, build_advantage=0.3, stabilize=0.9)

        self.assertIs(state.objective, STABILIZE)
        self.assertIs(state.previous, BUILD_ADVANTAGE)
        self.assertEqual(state.entered_at, 1.0)

    def test_the_emergency_still_needs_the_margin(self):
        state = select(
            self.state, 1.0, threat=0.95, build_advantage=0.5, stabilize=0.55
        )

        self.assertIs(state, self.state)

    def test_the_emergency_is_only_for_stabilize(self):
        state = select(self.state, 1.0, threat=0.95, build_advantage=0.1, recover=0.9)

        self.assertIs(state, self.state)

    def test_a_threat_below_the_emergency_waits_for_the_dwell(self):
        state = select(
            self.state,
            1.0,
            threat=CONFIG.emergency_threat - 0.01,  # type: ignore[operator]
            build_advantage=0.1,
            stabilize=0.9,
        )

        self.assertIs(state, self.state)

    def test_the_emergency_can_be_disabled(self):
        config = replace(CONFIG, emergency_threat=None)

        state = select(self.state, 1.0, threat=1.0, config=config, stabilize=1.0)

        self.assertIs(state, self.state)

    def test_equal_challengers_resolve_to_the_more_conservative_objective(self):
        state = select(self.state, DWELL, stabilize=0.9, recover=0.9, pressure=0.9)

        self.assertIs(state.objective, STABILIZE)


class DecisionConfidenceTests(unittest.TestCase):
    def test_confidence_is_the_lead_over_the_best_other_objective(self):
        lead = CONFIG.clear_lead

        self.assertEqual(
            decision_confidence(
                PRESSURE, assessments(pressure=0.5 + lead, recover=0.5), CONFIG
            ),
            1.0,
        )
        self.assertAlmostEqual(
            decision_confidence(
                PRESSURE, assessments(pressure=0.5 + lead / 2, recover=0.5), CONFIG
            ),
            0.5,
        )
        self.assertEqual(
            decision_confidence(
                PRESSURE, assessments(pressure=0.5, recover=0.5), CONFIG
            ),
            0.0,
        )

    def test_an_objective_held_against_a_better_score_has_no_confidence(self):
        self.assertEqual(
            decision_confidence(
                BUILD_ADVANTAGE, assessments(build_advantage=0.4, pressure=0.9), CONFIG
            ),
            0.0,
        )


class DirectorColdStartTests(unittest.TestCase):
    def test_no_snapshot_before_the_first_update(self):
        self.assertIsNone(StrategicDirector().snapshot)

    def test_first_update_builds_advantage(self):
        director = StrategicDirector()

        snapshot = director.update(COLD_START, 0.0)

        self.assertIs(snapshot.objective, BUILD_ADVANTAGE)
        self.assertIsNone(snapshot.previous_objective)
        self.assertEqual(snapshot.time_in_objective, 0.0)
        self.assertGreater(snapshot.confidence, 0.0)
        self.assertIs(director.snapshot, snapshot)

    def test_first_update_holds_the_initial_objective_against_a_better_score(self):
        snapshot = StrategicDirector().update(MAP_CONTROL, 0.0)

        self.assertIs(snapshot.objective, BUILD_ADVANTAGE)
        self.assertIs(snapshot.leader, TAKE_MAP_CONTROL)
        self.assertEqual(snapshot.confidence, 0.0)

    def test_a_critical_threat_at_the_first_update_stabilizes_at_once(self):
        snapshot = StrategicDirector().update(HIGH_THREAT, 0.0)

        self.assertIs(snapshot.objective, STABILIZE)
        self.assertIs(snapshot.previous_objective, BUILD_ADVANTAGE)

    def test_the_initial_objective_is_configurable(self):
        config = replace(CONFIG, initial_objective=RECOVER)

        self.assertIs(
            StrategicDirector(config).update(COLD_START, 0.0).objective, RECOVER
        )


class DirectorHysteresisTests(unittest.TestCase):
    def test_alternating_leaders_do_not_flip_flop_the_objective(self):
        director = StrategicDirector()
        snapshots = [
            director.update(MAP_CONTROL if second % 2 else EVEN_STABLE, float(second))
            for second in range(61)
        ]
        leader_changes = sum(
            1
            for a, b in zip(snapshots, snapshots[1:], strict=False)
            if a.leader is not b.leader
        )
        switch_times = [
            b.game_time
            for a, b in zip(snapshots, snapshots[1:], strict=False)
            if a.objective is not b.objective
        ]

        self.assertEqual(leader_changes, 60)
        self.assertLessEqual(len(switch_times), 60 / DWELL)
        for earlier, later in zip(switch_times, switch_times[1:], strict=False):
            self.assertGreaterEqual(later - earlier, DWELL)

    def test_a_lead_inside_the_margin_never_switches(self):
        current = scores(NEAR_TIE)
        self.assertGreater(current[TAKE_MAP_CONTROL], current[BUILD_ADVANTAGE])
        self.assertLess(
            current[TAKE_MAP_CONTROL] - current[BUILD_ADVANTAGE], CONFIG.switch_margin
        )

        snapshots = run(StrategicDirector(), NEAR_TIE, 0, 120)

        self.assertTrue(all(item.objective is BUILD_ADVANTAGE for item in snapshots))
        self.assertIs(snapshots[-1].leader, TAKE_MAP_CONTROL)

    def test_the_same_lead_switches_without_a_margin(self):
        director = StrategicDirector(replace(CONFIG, switch_margin=0.0))

        snapshots = run(director, NEAR_TIE, 0, DWELL)

        self.assertIs(snapshots[-1].objective, TAKE_MAP_CONTROL)

    def test_a_clear_lasting_lead_switches_once_the_dwell_is_over(self):
        director = StrategicDirector()
        run(director, EVEN_STABLE, 0, 4)

        held = run(director, MAP_CONTROL, 5, DWELL - 1)
        switched = director.update(MAP_CONTROL, DWELL)
        later = director.update(MAP_CONTROL, DWELL + 5)

        self.assertTrue(all(item.objective is BUILD_ADVANTAGE for item in held))
        self.assertTrue(all(item.leader is TAKE_MAP_CONTROL for item in held))
        self.assertIs(switched.objective, TAKE_MAP_CONTROL)
        self.assertIs(switched.previous_objective, BUILD_ADVANTAGE)
        self.assertEqual(switched.time_in_objective, 0.0)
        self.assertGreater(switched.confidence, 0.0)
        self.assertEqual(later.time_in_objective, 5.0)
        self.assertIs(later.previous_objective, BUILD_ADVANTAGE)

    def test_a_critical_threat_stabilizes_before_the_dwell_is_over(self):
        director = StrategicDirector()
        self.assertIs(run(director, PRESSURE_READY, 0, DWELL)[-1].objective, PRESSURE)

        snapshot = director.update(HIGH_THREAT, DWELL + 1)

        self.assertIs(snapshot.objective, STABILIZE)
        self.assertIs(snapshot.previous_objective, PRESSURE)

    def test_a_moderate_threat_waits_for_the_dwell(self):
        director = StrategicDirector()
        run(director, PRESSURE_READY, 0, DWELL)

        held = run(director, MODERATE_THREAT, DWELL + 1, 2 * DWELL - 1)
        switched = director.update(MODERATE_THREAT, 2 * DWELL)

        self.assertTrue(all(item.objective is PRESSURE for item in held))
        self.assertTrue(all(item.leader is STABILIZE for item in held))
        self.assertIs(switched.objective, STABILIZE)

    def test_leaving_an_emergency_stabilize_still_takes_the_dwell(self):
        director = StrategicDirector()
        director.update(HIGH_THREAT, 0.0)

        calm = run(director, EVEN_STABLE, 1, DWELL - 1)
        released = director.update(EVEN_STABLE, DWELL)

        self.assertTrue(all(item.objective is STABILIZE for item in calm))
        self.assertIs(released.objective, BUILD_ADVANTAGE)


class DirectorCadenceTests(unittest.TestCase):
    def test_updates_inside_the_interval_reuse_the_last_snapshot(self):
        director = StrategicDirector()
        first = director.update(EVEN_STABLE, 10.0)

        self.assertIs(director.update(HIGH_THREAT, 10.5), first)
        refreshed = director.update(HIGH_THREAT, 11.0)

        self.assertIsNot(refreshed, first)
        self.assertEqual(refreshed.game_time, 11.0)
        self.assertEqual(refreshed.inputs, HIGH_THREAT)

    def test_a_zero_interval_recomputes_every_update(self):
        director = StrategicDirector(replace(CONFIG, update_interval_seconds=0.0))
        first = director.update(EVEN_STABLE, 10.0)

        self.assertIsNot(director.update(EVEN_STABLE, 10.0), first)

    def test_game_time_must_be_finite_and_never_go_backwards(self):
        director = StrategicDirector()
        director.update(EVEN_STABLE, 10.0)

        with self.assertRaises(ValueError):
            director.update(EVEN_STABLE, 9.0)
        with self.assertRaises(ValueError):
            director.update(EVEN_STABLE, float("nan"))


class DirectorDeterminismTests(unittest.TestCase):
    SCRIPT = (
        [(EVEN_STABLE, t) for t in range(0, 10)]
        + [(MAP_CONTROL, t) for t in range(10, 40)]
        + [(PRESSURE_READY, t) for t in range(40, 70)]
        + [(HIGH_THREAT, t) for t in range(70, 75)]
        + [(NEAR_TIE, t) for t in range(75, 120)]
    )

    def play(self) -> list[StrategySnapshot]:
        director = StrategicDirector()
        return [director.update(inputs, float(t)) for inputs, t in self.SCRIPT]

    def test_the_same_game_always_yields_the_same_snapshots(self):
        first = self.play()

        self.assertEqual(first, self.play())
        # After the emergency, NEAR_TIE's best challenger to STABILIZE is
        # TAKE_MAP_CONTROL, adopted once STABILIZE's dwell is over.
        self.assertEqual(
            [item.objective for item in first if item.time_in_objective == 0.0][1:],
            [TAKE_MAP_CONTROL, PRESSURE, STABILIZE, TAKE_MAP_CONTROL],
        )


class SnapshotContractTests(unittest.TestCase):
    def test_a_snapshot_decides_direction_never_execution(self):
        self.assertEqual(
            {item.name for item in fields(StrategySnapshot)},
            {
                "objective",
                "confidence",
                "assessments",
                "previous_objective",
                "game_time",
                "time_in_objective",
                "inputs",
            },
        )

    def test_a_snapshot_reads_every_objective_score(self):
        snapshot = StrategicDirector().update(PRESSURE_READY, 0.0)

        self.assertEqual(
            [item.objective for item in snapshot.assessments], list(StrategicObjective)
        )
        self.assertEqual(snapshot.score(PRESSURE), snapshot.assessment(PRESSURE).score)
        self.assertEqual(scores(PRESSURE_READY)[PRESSURE], snapshot.score(PRESSURE))


class ConfigValidationTests(unittest.TestCase):
    def test_invalid_numbers_are_rejected(self):
        invalid: tuple[dict[str, Any], ...] = (
            {"update_interval_seconds": -1.0},
            {"minimum_dwell_seconds": float("inf")},
            {"switch_margin": -0.1},
            {"switch_margin": 1.5},
            {"emergency_threat": 1.2},
            {"clear_lead": 0.0},
        )
        for overrides in invalid:
            with self.subTest(**overrides), self.assertRaises(ValueError):
                replace(CONFIG, **overrides)

    def test_weights_must_be_non_negative_magnitudes(self):
        with self.assertRaises(ValueError):
            StabilizeWeights(immediate_threat=-0.1)
        with self.assertRaises(ValueError):
            StabilizeWeights(base_exposure=float("nan"))
        with self.assertRaises(ValueError):
            TakeMapControlWeights(military_sufficient=0.0)


if __name__ == "__main__":
    unittest.main()

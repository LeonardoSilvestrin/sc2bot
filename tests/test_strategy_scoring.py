"""Objective scoring: each objective rises and falls with the signals it is
about. Tests compare objectives with each other rather than pinning exact
scores, so retuning a weight only breaks a test when it changes a decision."""

from __future__ import annotations

import itertools
import math
import unittest

from bot.strategy import StrategicObjective, StrategyConfig, StrategyInputs
from bot.strategy.model import SIGNAL_RANGES, ObjectiveAssessment, leading
from bot.strategy.scoring import assess_objectives, home_security

CONFIG = StrategyConfig()

STABILIZE = StrategicObjective.STABILIZE
RECOVER = StrategicObjective.RECOVER
BUILD_ADVANTAGE = StrategicObjective.BUILD_ADVANTAGE
TAKE_MAP_CONTROL = StrategicObjective.TAKE_MAP_CONTROL
PRESSURE = StrategicObjective.PRESSURE


def signals(
    *,
    military_edge: float = 0.0,
    economic_edge: float = 0.0,
    territory_edge: float = 0.0,
    immediate_threat: float = 0.0,
    base_exposure: float = 0.1,
    knowledge_confidence: float = 0.6,
) -> StrategyInputs:
    """An even, quiet position we know reasonably well, unless overridden."""

    return StrategyInputs(
        military_edge=military_edge,
        economic_edge=economic_edge,
        territory_edge=territory_edge,
        immediate_threat=immediate_threat,
        base_exposure=base_exposure,
        knowledge_confidence=knowledge_confidence,
    )


COLD_START = StrategyInputs(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
EVEN_STABLE = signals()
HIGH_THREAT = signals(immediate_threat=0.9, base_exposure=0.6)
BEHIND = signals(
    military_edge=-0.5, economic_edge=-0.5, immediate_threat=0.1, base_exposure=0.2
)
MAP_CONTROL = signals(military_edge=0.4, economic_edge=0.1, immediate_threat=0.05)
PRESSURE_READY = signals(
    military_edge=0.8,
    economic_edge=0.3,
    territory_edge=0.4,
    base_exposure=0.05,
    knowledge_confidence=0.9,
)
SCENARIOS = (COLD_START, EVEN_STABLE, HIGH_THREAT, BEHIND, MAP_CONTROL, PRESSURE_READY)


def assess(inputs: StrategyInputs) -> tuple[ObjectiveAssessment, ...]:
    return assess_objectives(inputs, CONFIG)


def scores(inputs: StrategyInputs) -> dict[StrategicObjective, float]:
    return {item.objective: item.score for item in assess(inputs)}


def leader(inputs: StrategyInputs) -> StrategicObjective:
    return leading(assess(inputs)).objective


def best_other(inputs: StrategyInputs, objective: StrategicObjective) -> float:
    return max(score for key, score in scores(inputs).items() if key is not objective)


def by_objective(
    inputs: StrategyInputs, objective: StrategicObjective
) -> ObjectiveAssessment:
    return next(item for item in assess(inputs) if item.objective is objective)


def non_decreasing(values: list[float]) -> bool:
    return all(
        later >= earlier - 1e-12 for earlier, later in itertools.pairwise(values)
    )


def non_increasing(values: list[float]) -> bool:
    return non_decreasing([-value for value in values])


class ObjectiveScenarioTests(unittest.TestCase):
    def test_high_immediate_threat_makes_stabilize_dominant(self):
        self.assertIs(leader(HIGH_THREAT), STABILIZE)
        self.assertGreaterEqual(
            scores(HIGH_THREAT)[STABILIZE] - best_other(HIGH_THREAT, STABILIZE), 0.3
        )
        self.assertGreaterEqual(
            scores(HIGH_THREAT)[STABILIZE] - scores(EVEN_STABLE)[STABILIZE], 0.5
        )

    def test_rising_threat_raises_stabilize_and_lowers_every_ambition(self):
        readings = [
            scores(signals(immediate_threat=step / 10, military_edge=0.4))
            for step in range(11)
        ]

        self.assertTrue(non_decreasing([item[STABILIZE] for item in readings]))
        for objective in (BUILD_ADVANTAGE, TAKE_MAP_CONTROL, PRESSURE):
            self.assertTrue(non_increasing([item[objective] for item in readings]))

    def test_a_crisis_stabilizes_even_when_we_are_ahead(self):
        inputs = signals(
            military_edge=0.5,
            immediate_threat=0.85,
            base_exposure=0.4,
            knowledge_confidence=0.8,
        )

        self.assertIs(leader(inputs), STABILIZE)

    def test_behind_without_emergency_favours_recover(self):
        current = scores(BEHIND)

        self.assertIs(leader(BEHIND), RECOVER)
        self.assertGreater(current[RECOVER], current[STABILIZE])
        self.assertGreater(current[RECOVER], current[BUILD_ADVANTAGE])
        self.assertGreater(current[RECOVER], scores(EVEN_STABLE)[RECOVER] + 0.3)

    def test_recover_yields_to_stabilize_in_a_crisis(self):
        crisis = signals(
            military_edge=-0.5,
            economic_edge=-0.5,
            immediate_threat=0.8,
            base_exposure=0.7,
        )

        self.assertIs(leader(crisis), STABILIZE)
        self.assertLess(scores(crisis)[RECOVER], scores(BEHIND)[RECOVER])

    def test_even_and_stable_builds_advantage(self):
        for confidence in (0.2, 0.6, 0.9):
            with self.subTest(knowledge_confidence=confidence):
                inputs = signals(knowledge_confidence=confidence)
                self.assertIs(leader(inputs), BUILD_ADVANTAGE)
                self.assertGreater(
                    scores(inputs)[BUILD_ADVANTAGE]
                    - best_other(inputs, BUILD_ADVANTAGE),
                    CONFIG.switch_margin,
                )

    def test_cold_start_without_information_builds_advantage(self):
        current = scores(COLD_START)

        self.assertIs(leader(COLD_START), BUILD_ADVANTAGE)
        self.assertLess(current[PRESSURE], 0.1)
        self.assertLess(current[TAKE_MAP_CONTROL], current[BUILD_ADVANTAGE])

    def test_less_knowledge_never_reads_as_a_weaker_enemy(self):
        readings = [
            scores(signals(military_edge=0.8, knowledge_confidence=step / 10))
            for step in range(11)
        ]

        self.assertTrue(non_decreasing([item[PRESSURE] for item in readings]))
        self.assertTrue(non_increasing([item[BUILD_ADVANTAGE] for item in readings]))

    def test_sufficient_army_safe_home_and_open_territory_favour_map_control(self):
        current = scores(MAP_CONTROL)

        self.assertIs(leader(MAP_CONTROL), TAKE_MAP_CONTROL)
        self.assertGreater(current[TAKE_MAP_CONTROL], current[BUILD_ADVANTAGE])
        self.assertGreater(current[TAKE_MAP_CONTROL], current[PRESSURE])

    def test_map_control_wants_territory_left_to_take(self):
        contested = signals(military_edge=0.4, territory_edge=-0.4)
        dominated = signals(military_edge=0.4, territory_edge=0.9)

        self.assertGreater(
            scores(contested)[TAKE_MAP_CONTROL], scores(dominated)[TAKE_MAP_CONTROL]
        )

    def test_map_control_needs_an_army(self):
        self.assertLess(
            scores(signals(territory_edge=-0.8))[TAKE_MAP_CONTROL],
            scores(MAP_CONTROL)[TAKE_MAP_CONTROL],
        )
        self.assertIsNot(leader(signals(territory_edge=-0.8)), TAKE_MAP_CONTROL)

    def test_strong_confident_edge_at_a_safe_home_favours_pressure(self):
        current = scores(PRESSURE_READY)

        self.assertIs(leader(PRESSURE_READY), PRESSURE)
        self.assertGreater(current[PRESSURE], current[BUILD_ADVANTAGE])
        self.assertGreater(current[PRESSURE], current[TAKE_MAP_CONTROL])

    def test_low_confidence_clearly_lowers_pressure(self):
        uncertain = signals(
            military_edge=0.8,
            economic_edge=0.3,
            territory_edge=0.4,
            base_exposure=0.05,
            knowledge_confidence=0.2,
        )

        self.assertIsNot(leader(uncertain), PRESSURE)
        self.assertGreaterEqual(
            scores(PRESSURE_READY)[PRESSURE] - scores(uncertain)[PRESSURE], 0.3
        )
        self.assertLess(scores(uncertain)[PRESSURE], scores(uncertain)[BUILD_ADVANTAGE])

    def test_pressure_needs_a_military_edge(self):
        no_army = signals(
            economic_edge=0.8, territory_edge=0.8, knowledge_confidence=1.0
        )

        self.assertIsNot(leader(no_army), PRESSURE)


class ExplainabilityTests(unittest.TestCase):
    def test_every_score_is_its_clamped_contributions(self):
        for inputs in SCENARIOS:
            for item in assess(inputs):
                with self.subTest(inputs=inputs, objective=item.objective):
                    raw = sum(entry.contribution for entry in item.contributions)
                    self.assertTrue(math.isclose(item.raw_score, raw))
                    self.assertTrue(
                        math.isclose(item.score, min(max(raw, 0.0), 1.0), abs_tol=1e-12)
                    )

    def test_each_signal_is_reported_once(self):
        for inputs in SCENARIOS:
            for item in assess(inputs):
                names = [entry.signal for entry in item.contributions]
                self.assertEqual(len(names), len(set(names)), item.objective)

    def test_threat_is_the_main_reason_to_stabilize(self):
        stabilize = by_objective(HIGH_THREAT, STABILIZE)
        top = max(stabilize.contributions, key=lambda entry: entry.contribution)

        self.assertEqual(top.signal, "immediate_threat")
        self.assertEqual(stabilize.contribution("economic_edge"), 0.0)

    def test_pressure_reports_what_low_confidence_takes_back(self):
        def discount(confidence: float) -> float:
            inputs = signals(military_edge=0.8, knowledge_confidence=confidence)
            return by_objective(inputs, PRESSURE).contribution("knowledge_confidence")

        pressure = by_objective(PRESSURE_READY, PRESSURE)

        self.assertGreater(pressure.contribution("military_edge"), 0.0)
        self.assertLess(pressure.contribution("immediate_threat"), 1e-12)
        self.assertLess(discount(0.2), discount(0.6))
        self.assertLess(discount(0.6), 0.0)
        self.assertEqual(discount(1.0), 0.0)

    def test_assessments_follow_objective_order(self):
        self.assertEqual(
            [item.objective for item in assess(EVEN_STABLE)], list(StrategicObjective)
        )


class BoundaryTests(unittest.TestCase):
    def test_scores_stay_within_the_unit_interval_at_every_extreme(self):
        edges = (-1.0, 0.0, 1.0)
        units = (0.0, 1.0)
        for values in itertools.product(edges, edges, edges, units, units, units):
            inputs = StrategyInputs(*values)
            for item in assess(inputs):
                with self.subTest(inputs=inputs, objective=item.objective):
                    self.assertTrue(math.isfinite(item.raw_score))
                    self.assertGreaterEqual(item.score, 0.0)
                    self.assertLessEqual(item.score, 1.0)

    def test_everything_lost_under_full_threat_stabilizes(self):
        self.assertIs(
            leader(StrategyInputs(-1.0, -1.0, -1.0, 1.0, 1.0, 1.0)), STABILIZE
        )

    def test_everything_won_at_a_safe_home_pressures(self):
        self.assertIs(leader(StrategyInputs(1.0, 1.0, 1.0, 0.0, 0.0, 1.0)), PRESSURE)

    def test_the_same_edge_with_no_knowledge_does_not_pressure(self):
        self.assertIsNot(leader(StrategyInputs(1.0, 1.0, 1.0, 0.0, 0.0, 0.0)), PRESSURE)

    def test_inputs_accept_their_exact_bounds(self):
        StrategyInputs(-1.0, -1.0, -1.0, 0.0, 0.0, 0.0)
        StrategyInputs(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)

    def test_inputs_reject_out_of_range_and_nan(self):
        base = dict.fromkeys(SIGNAL_RANGES, 0.0)
        for name, (low, high) in SIGNAL_RANGES.items():
            for value in (low - 0.01, high + 0.01, math.nan, math.inf):
                with (
                    self.subTest(signal=name, value=value),
                    self.assertRaises(ValueError),
                ):
                    StrategyInputs(**{**base, name: value})

    def test_clamped_inputs_pull_drift_back_into_range(self):
        inputs = StrategyInputs.clamped(
            military_edge=1.2,
            economic_edge=-1.0000001,
            territory_edge=0.3,
            immediate_threat=-0.1,
            base_exposure=1.5,
            knowledge_confidence=0.5,
        )

        self.assertEqual(inputs, StrategyInputs(1.0, -1.0, 0.3, 0.0, 1.0, 0.5))
        with self.assertRaises(ValueError):
            StrategyInputs.clamped(
                military_edge=math.nan,
                economic_edge=0.0,
                territory_edge=0.0,
                immediate_threat=0.0,
                base_exposure=0.0,
                knowledge_confidence=0.0,
            )

    def test_home_security_is_lost_to_either_threat_or_exposure(self):
        self.assertEqual(home_security(signals(base_exposure=0.0)), 1.0)
        self.assertEqual(home_security(signals(immediate_threat=1.0)), 0.0)
        self.assertEqual(home_security(signals(base_exposure=1.0)), 0.0)


class DeterminismTests(unittest.TestCase):
    def test_the_same_inputs_always_score_the_same(self):
        for inputs in SCENARIOS:
            self.assertEqual(assess(inputs), assess(inputs))
            self.assertEqual(
                assess(inputs), assess_objectives(inputs, StrategyConfig())
            )


if __name__ == "__main__":
    unittest.main()

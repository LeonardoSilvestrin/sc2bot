from __future__ import annotations

import math
import unittest

from bot.strategy import (
    IntentConfig,
    ObjectiveAssessment,
    StrategicActivity,
    StrategicIntent,
    StrategicObjective,
    StrategyInputs,
    StrategySnapshot,
    derive_intent,
)

NEUTRAL_INPUTS = StrategyInputs(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def strategy(
    objective: StrategicObjective, **scores: float
) -> StrategySnapshot:
    return StrategySnapshot(
        objective=objective,
        confidence=0.5,
        assessments=tuple(
            ObjectiveAssessment(item, scores.get(item.name.lower(), 0.0), ())
            for item in StrategicObjective
        ),
        previous_objective=None,
        game_time=100.0,
        time_in_objective=30.0,
        inputs=NEUTRAL_INPUTS,
    )


class StrategicIntentContractTests(unittest.TestCase):
    def test_values_are_normalized_and_nan_is_rejected(self):
        for bad in (-0.1, 1.1, math.nan):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                StrategicIntent(0.5, 0.5, bad, 0.5, 0.5)

    def test_desirability_reads_the_activity_preference(self):
        intent = StrategicIntent(
            defense=0.1, map_control=0.2, harass=0.3, information=0.4,
            risk_tolerance=0.5,
        )

        self.assertEqual(
            [intent.desirability(activity) for activity in StrategicActivity],
            [0.1, 0.2, 0.3, 0.4],
        )


class IntentMappingTests(unittest.TestCase):
    def setUp(self):
        self.config = IntentConfig()

    def profile(self, objective: StrategicObjective) -> StrategicIntent:
        return self.config.profile(objective)

    def test_stabilize_defends_and_avoids_risk(self):
        stabilize = self.profile(StrategicObjective.STABILIZE)
        for objective in StrategicObjective:
            if objective is StrategicObjective.STABILIZE:
                continue
            other = self.profile(objective)
            with self.subTest(objective=objective.name):
                self.assertGreater(stabilize.defense, other.defense)
                self.assertLess(stabilize.risk_tolerance, other.risk_tolerance)
        self.assertLess(stabilize.map_control, stabilize.defense)
        self.assertLess(stabilize.harass, stabilize.defense)

    def test_take_map_control_wants_space_and_information(self):
        control = self.profile(StrategicObjective.TAKE_MAP_CONTROL)
        for objective in StrategicObjective:
            if objective is StrategicObjective.TAKE_MAP_CONTROL:
                continue
            with self.subTest(objective=objective.name):
                self.assertGreater(
                    control.map_control, self.profile(objective).map_control
                )
                self.assertGreaterEqual(
                    control.information, self.profile(objective).information
                )

    def test_pressure_harasses_accepts_risk_and_still_defends(self):
        pressure = self.profile(StrategicObjective.PRESSURE)
        for objective in StrategicObjective:
            if objective is StrategicObjective.PRESSURE:
                continue
            with self.subTest(objective=objective.name):
                self.assertGreater(pressure.harass, self.profile(objective).harass)
                self.assertGreater(
                    pressure.risk_tolerance, self.profile(objective).risk_tolerance
                )
        self.assertGreater(pressure.defense, 0.0)
        self.assertGreater(
            pressure.map_control,
            self.profile(StrategicObjective.BUILD_ADVANTAGE).map_control,
        )

    def test_the_default_state_ranks_harass_above_map_control(self):
        """The ordering the old fixed priorities encoded (62 over 40) is now a
        strategic preference of BUILD_ADVANTAGE, not a planner constant."""

        build = self.profile(StrategicObjective.BUILD_ADVANTAGE)

        self.assertGreater(build.harass, build.map_control)


class DeriveIntentTests(unittest.TestCase):
    def test_no_snapshot_yet_reads_the_fallback_objective(self):
        self.assertEqual(
            derive_intent(None),
            IntentConfig().profile(StrategicObjective.BUILD_ADVANTAGE),
        )

    def test_without_scores_the_intent_is_the_held_profile(self):
        for objective in StrategicObjective:
            with self.subTest(objective=objective.name):
                self.assertEqual(
                    derive_intent(strategy(objective)),
                    IntentConfig().profile(objective),
                )

    def test_a_close_challenger_shades_the_intent_smoothly(self):
        config = IntentConfig()
        held = config.profile(StrategicObjective.BUILD_ADVANTAGE)
        challenger = config.profile(StrategicObjective.PRESSURE)

        alone = derive_intent(
            strategy(StrategicObjective.BUILD_ADVANTAGE, build_advantage=0.6)
        )
        shaded = derive_intent(
            strategy(
                StrategicObjective.BUILD_ADVANTAGE,
                build_advantage=0.6,
                pressure=0.55,
            )
        )

        self.assertEqual(alone, held)
        self.assertGreater(shaded.harass, held.harass)
        self.assertLess(shaded.harass, challenger.harass)

    def test_the_objective_in_force_still_dominates_a_better_leader(self):
        """Hysteresis holds STABILIZE against a PRESSURE leader: the intent
        keeps defending until Strategy actually switches."""

        intent = derive_intent(
            strategy(StrategicObjective.STABILIZE, stabilize=0.2, pressure=0.8)
        )

        self.assertGreater(intent.defense, intent.harass)

    def test_every_derived_value_stays_normalized(self):
        intent = derive_intent(
            strategy(
                StrategicObjective.PRESSURE,
                **{item.name.lower(): 1.0 for item in StrategicObjective},
            ),
            IntentConfig(held_share=0.0),
        )

        for value in intent.as_dict().values():
            self.assertTrue(0.0 <= value <= 1.0)


if __name__ == "__main__":
    unittest.main()

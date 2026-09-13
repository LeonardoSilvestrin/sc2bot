"""The central Mission Policy: one scale for every behavior's opportunities."""

from __future__ import annotations

import itertools
import math
import unittest
from dataclasses import replace

from bot.engine.missions.allocator import UnitAllocator
from bot.strategy import (
    FALLBACK_OWNER,
    MINIMUM_CONTROL_ALIGNMENT,
    REJECTED_NEGATIVE_RAW_UTILITY,
    REJECTED_UTILITY_NOT_ABOVE_MINIMUM,
    VIABLE_BY_URGENCY_FLOOR,
    VIABLE_POSITIVE_UTILITY,
    ControlMatch,
    ControlNeed,
    IntentConfig,
    MissionPolicyConfig,
    MissionSignals,
    StrategicActivity,
    StrategicIntent,
    StrategicObjective,
    evaluate_mission,
    is_viable,
    to_priority,
)

PROFILES = IntentConfig()
PRESSURE = PROFILES.profile(StrategicObjective.PRESSURE)
STABILIZE = PROFILES.profile(StrategicObjective.STABILIZE)
BUILD = PROFILES.profile(StrategicObjective.BUILD_ADVANTAGE)


def critical_defense() -> MissionSignals:
    """Thirty Roaches in the natural."""

    return MissionSignals(
        activity=StrategicActivity.DEFENSE, opportunity=0.9, urgency=1.0, risk=0.2
    )


def good_harass() -> MissionSignals:
    """Hellions at an exposed mineral line."""

    return MissionSignals(
        activity=StrategicActivity.HARASS,
        opportunity=0.9,
        urgency=0.2,
        risk=0.25,
        information_gain=0.1,
    )


def low_urgency_defense() -> MissionSignals:
    return MissionSignals(
        activity=StrategicActivity.DEFENSE, opportunity=0.4, urgency=0.3, risk=0.2
    )


def with_intent(base: StrategicIntent, **changes: float) -> StrategicIntent:
    return StrategicIntent(**{**base.as_dict(), **changes})


class MissionSignalsContractTests(unittest.TestCase):
    def test_every_signal_is_normalized(self):
        for name in ("opportunity", "urgency", "risk", "information_gain"):
            for bad in (-0.01, 1.01, math.nan):
                with self.subTest(signal=name, value=bad), self.assertRaises(
                    ValueError
                ):
                    MissionSignals(activity=StrategicActivity.HARASS, **{name: bad})

    def test_work_serving_no_objective_is_a_valid_signal(self):
        signals = MissionSignals(activity=StrategicActivity.HARASS, opportunity=0.5)

        self.assertIsNone(signals.control)
        self.assertIsNone(signals.log_fields()["control_objective"])


class ControlMatchContractTests(unittest.TestCase):
    """An objective id never travels with a negligible alignment."""

    def test_a_match_names_its_objective(self):
        with self.assertRaises(ValueError):
            ControlMatch(objective_id="  ", alignment=1.0)

    def test_a_match_below_the_semantic_minimum_cannot_exist(self):
        for bad in (0.0, 1e-9, MINIMUM_CONTROL_ALIGNMENT - 1e-6, 1.01, math.nan):
            with self.subTest(alignment=bad), self.assertRaises(ValueError):
                ControlMatch(objective_id="region:west", alignment=bad)

    def test_from_alignment_reports_no_match_for_a_weak_association(self):
        self.assertIsNone(ControlMatch.from_alignment("region:west", 1e-9))
        self.assertIsNone(
            ControlMatch.from_alignment(
                "region:west", MINIMUM_CONTROL_ALIGNMENT - 1e-6
            )
        )
        self.assertEqual(
            ControlMatch.from_alignment("region:west", MINIMUM_CONTROL_ALIGNMENT),
            ControlMatch("region:west", MINIMUM_CONTROL_ALIGNMENT),
        )
        with self.assertRaises(ValueError):
            ControlMatch.from_alignment("region:west", math.nan)

    def test_no_match_prices_no_control_even_when_the_objective_has_a_need(self):
        need = ControlNeed(importance=1.0, gap=1.0)
        unmatched = MissionSignals(
            activity=StrategicActivity.MAP_CONTROL, opportunity=0.5
        )
        matched = MissionSignals(
            activity=StrategicActivity.MAP_CONTROL,
            opportunity=0.5,
            control=ControlMatch("region:west", 1.0),
        )

        self.assertEqual(
            evaluate_mission(unmatched, BUILD, need=need).control_contribution, 0.0
        )
        self.assertGreater(
            evaluate_mission(matched, BUILD, need=need).control_contribution, 0.0
        )
        # A match to an objective the context no longer holds prices nothing.
        self.assertEqual(evaluate_mission(matched, BUILD).control_contribution, 0.0)

    def test_signals_carry_no_priority(self):
        self.assertNotIn("priority", MissionSignals.__dataclass_fields__)


class CrossBehaviorRankingTests(unittest.TestCase):
    def test_critical_defense_outranks_harass_even_under_pressure(self):
        """A stale aggressive preference never buries an obvious emergency."""

        defense = evaluate_mission(critical_defense(), PRESSURE)
        harass = evaluate_mission(good_harass(), PRESSURE)

        self.assertGreater(defense.priority, harass.priority)
        self.assertTrue(defense.floor_applied)
        self.assertGreaterEqual(defense.utility, 0.95)

    def test_critical_defense_clears_a_striking_raid_by_the_preemption_margin(self):
        """Mid-strike Banshees add their executor cost to the margin; a base
        under full attack still takes them."""

        defense = evaluate_mission(
            critical_defense(), with_intent(PRESSURE, defense=0.0)
        )
        harass = evaluate_mission(
            MissionSignals(
                activity=StrategicActivity.HARASS, opportunity=1.0, urgency=0.5
            ),
            with_intent(PRESSURE, harass=1.0, risk_tolerance=1.0),
        )

        self.assertGreaterEqual(
            defense.priority,
            harass.priority + UnitAllocator().preemption_margin + 5,
        )

    def test_good_harass_outranks_low_urgency_defense_when_strategy_presses(self):
        harass = evaluate_mission(good_harass(), PRESSURE)
        defense = evaluate_mission(low_urgency_defense(), PRESSURE)

        self.assertGreater(harass.priority, defense.priority)

    def test_the_default_state_keeps_a_raid_above_the_patrol_by_the_margin(self):
        """Banshees and Reapers also suit the patrol's role: a ready raid of
        the same local quality must still be able to take them back."""

        raid = MissionSignals(
            activity=StrategicActivity.HARASS,
            opportunity=0.7,
            urgency=0.2,
            risk=0.2,
            information_gain=0.3,
        )
        patrol = MissionSignals(
            activity=StrategicActivity.MAP_CONTROL,
            opportunity=0.7,
            risk=0.1,
            information_gain=0.3,
        )

        self.assertGreaterEqual(
            evaluate_mission(raid, BUILD).priority,
            evaluate_mission(patrol, BUILD).priority
            + UnitAllocator().preemption_margin,
        )

    def test_the_same_pair_flips_when_strategy_stabilizes(self):
        harass = evaluate_mission(good_harass(), STABILIZE)
        defense = evaluate_mission(low_urgency_defense(), STABILIZE)

        self.assertGreater(defense.priority, harass.priority)

    def test_higher_strategic_desirability_raises_utility(self):
        signals = good_harass()

        low = evaluate_mission(signals, with_intent(BUILD, harass=0.1))
        high = evaluate_mission(signals, with_intent(BUILD, harass=0.9))

        self.assertGreater(high.utility, low.utility)
        self.assertGreater(high.strategic_desirability, low.strategic_desirability)

    def test_higher_opportunity_raises_utility(self):
        weak = MissionSignals(activity=StrategicActivity.HARASS, opportunity=0.2)
        strong = MissionSignals(activity=StrategicActivity.HARASS, opportunity=0.8)

        self.assertGreater(
            evaluate_mission(strong, BUILD).utility,
            evaluate_mission(weak, BUILD).utility,
        )

    def test_urgency_raises_utility_more_strongly_than_opportunity(self):
        """Linearly at a typical desirability, and past the emergency point
        regardless of it (see the floor tests)."""

        base = MissionSignals(activity=StrategicActivity.DEFENSE, opportunity=0.5)
        opportune = MissionSignals(activity=StrategicActivity.DEFENSE, opportunity=0.8)
        urgent = MissionSignals(
            activity=StrategicActivity.DEFENSE, opportunity=0.5, urgency=0.3
        )

        start = evaluate_mission(base, BUILD).utility
        self.assertGreater(
            evaluate_mission(urgent, BUILD).utility - start,
            evaluate_mission(opportune, BUILD).utility - start,
        )

    def test_the_emergency_floor_is_continuous_in_urgency(self):
        utilities = [
            evaluate_mission(
                MissionSignals(activity=StrategicActivity.DEFENSE, urgency=value),
                with_intent(PRESSURE, defense=0.0),
            ).utility
            for value in (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
        ]

        self.assertEqual(utilities, sorted(utilities))
        for lower, upper in zip(utilities, utilities[1:], strict=False):
            self.assertLess(upper - lower, 0.25)

    def test_low_knowledge_with_an_information_intent_raises_scouting_utility(self):
        stale = MissionSignals(
            activity=StrategicActivity.INFORMATION,
            opportunity=0.5,
            information_gain=0.9,
            risk=0.2,
        )
        fresh = MissionSignals(
            activity=StrategicActivity.INFORMATION,
            opportunity=0.5,
            information_gain=0.1,
            risk=0.2,
        )
        curious = with_intent(BUILD, information=0.9)
        incurious = with_intent(BUILD, information=0.1)

        self.assertGreater(
            evaluate_mission(stale, curious).utility,
            evaluate_mission(fresh, curious).utility,
        )
        self.assertGreater(
            evaluate_mission(stale, curious).utility,
            evaluate_mission(stale, incurious).utility,
        )

    def test_information_gain_also_raises_map_control_utility(self):
        unknown = MissionSignals(
            activity=StrategicActivity.MAP_CONTROL,
            opportunity=0.5,
            information_gain=0.9,
        )
        known = MissionSignals(
            activity=StrategicActivity.MAP_CONTROL, opportunity=0.5
        )
        control = PROFILES.profile(StrategicObjective.TAKE_MAP_CONTROL)

        self.assertGreater(
            evaluate_mission(unknown, control).information_contribution,
            evaluate_mission(known, control).information_contribution,
        )

    def test_high_risk_is_penalized_more_under_low_risk_tolerance(self):
        risky = MissionSignals(
            activity=StrategicActivity.HARASS, opportunity=0.8, risk=0.9
        )

        cautious = evaluate_mission(risky, with_intent(BUILD, risk_tolerance=0.1))
        bold = evaluate_mission(risky, with_intent(BUILD, risk_tolerance=0.9))

        self.assertGreater(cautious.risk_penalty, bold.risk_penalty)
        self.assertLess(cautious.utility, bold.utility)
        # Some risk always counts, even fully tolerated.
        tolerant = evaluate_mission(risky, with_intent(BUILD, risk_tolerance=1.0))
        self.assertGreater(tolerant.risk_penalty, 0.0)

    def test_alignment_with_an_important_unsatisfied_objective_raises_utility(self):
        aligned = MissionSignals(
            activity=StrategicActivity.DEFENSE,
            opportunity=0.5,
            control=ControlMatch("passage:7", 1.0),
        )

        unsatisfied = evaluate_mission(
            aligned, BUILD, need=ControlNeed(importance=0.9, gap=0.8)
        )
        satisfied = evaluate_mission(
            aligned, BUILD, need=ControlNeed(importance=0.9, gap=0.0)
        )
        unimportant = evaluate_mission(
            aligned, BUILD, need=ControlNeed(importance=0.1, gap=0.8)
        )

        self.assertGreater(unsatisfied.utility, satisfied.utility)
        self.assertGreater(unsatisfied.utility, unimportant.utility)
        self.assertGreater(unsatisfied.control_contribution, 0.0)
        self.assertEqual(satisfied.control_contribution, 0.0)

    def test_the_breakdown_adds_up_to_the_raw_utility(self):
        ranking = evaluate_mission(
            MissionSignals(
                activity=StrategicActivity.MAP_CONTROL,
                opportunity=0.6,
                urgency=0.1,
                risk=0.3,
                information_gain=0.7,
                control=ControlMatch("region:north", 0.5),
            ),
            BUILD,
            need=ControlNeed(importance=0.7, gap=0.6),
        )

        self.assertFalse(ranking.floor_applied)
        self.assertAlmostEqual(ranking.utility, ranking.raw_utility)
        self.assertEqual(
            ranking.raw_utility,
            ranking.opportunity_contribution
            + ranking.information_contribution
            + ranking.control_contribution
            + ranking.urgency_contribution
            - ranking.risk_penalty,
        )
        self.assertEqual(ranking.control_need, ControlNeed(importance=0.7, gap=0.6))
        self.assertEqual(
            set(ranking.log_fields()),
            {
                "activity",
                "reason",
                "viable",
                "priority",
                "utility",
                "raw_utility",
                "urgency_floor",
                "floor_applied",
                "opportunity_contribution",
                "information_contribution",
                "control_contribution",
                "urgency_contribution",
                "risk_penalty",
                "strategic_desirability",
                "information_desire",
                "risk_tolerance",
                "control_importance",
                "control_gap",
            },
        )


class ViabilityTests(unittest.TestCase):
    """A candidate is proposed only when it is worth executing at all."""

    MARGIN = UnitAllocator().preemption_margin

    def test_zero_final_utility_is_rejected(self):
        evaluation = evaluate_mission(
            MissionSignals(activity=StrategicActivity.MAP_CONTROL), BUILD
        )

        self.assertEqual(evaluation.utility, 0.0)
        self.assertFalse(evaluation.viable)
        self.assertIsNone(evaluation.priority)
        self.assertEqual(evaluation.reason, REJECTED_UTILITY_NOT_ABOVE_MINIMUM)

    def test_negative_raw_utility_clamped_to_zero_is_rejected(self):
        evaluation = evaluate_mission(
            MissionSignals(activity=StrategicActivity.HARASS, risk=1.0),
            with_intent(PRESSURE, harass=0.0, risk_tolerance=0.0),
        )

        self.assertLess(evaluation.raw_utility, 0.0)
        self.assertEqual(evaluation.utility, 0.0)
        self.assertFalse(evaluation.viable)
        self.assertIsNone(evaluation.priority)
        self.assertEqual(evaluation.reason, REJECTED_NEGATIVE_RAW_UTILITY)

    def test_a_normal_positive_candidate_is_viable_above_the_fallback(self):
        evaluation = evaluate_mission(good_harass(), BUILD)

        self.assertTrue(evaluation.viable)
        self.assertEqual(evaluation.reason, VIABLE_POSITIVE_UTILITY)
        self.assertGreaterEqual(
            evaluation.priority, MissionPolicyConfig().fallback_priority + self.MARGIN
        )

    def test_urgent_defense_is_viable_through_its_floor_despite_negative_raw(self):
        evaluation = evaluate_mission(
            MissionSignals(activity=StrategicActivity.DEFENSE, urgency=0.6, risk=1.0),
            with_intent(PRESSURE, defense=0.0, risk_tolerance=0.0),
        )

        self.assertLess(evaluation.raw_utility, 0.0)
        self.assertTrue(evaluation.floor_applied)
        self.assertTrue(evaluation.viable)
        self.assertEqual(evaluation.reason, VIABLE_BY_URGENCY_FLOOR)
        self.assertGreaterEqual(
            evaluation.priority, MissionPolicyConfig().fallback_priority + self.MARGIN
        )

    def test_standing_is_accepted_at_its_fixed_fallback_priority(self):
        evaluation = evaluate_mission(MissionSignals.fallback("idle_army"), PRESSURE)

        self.assertTrue(evaluation.viable)
        self.assertEqual(evaluation.priority, MissionPolicyConfig().fallback_priority)
        self.assertEqual(evaluation.reason, FALLBACK_OWNER)

    def test_no_worthless_candidate_outranks_standing(self):
        """Every viable candidate clears the fallback owner by the preemption
        margin; every other one has no priority at all."""

        fallback = MissionPolicyConfig().fallback_priority
        indifferent = with_intent(
            BUILD,
            defense=0.0,
            map_control=0.0,
            harass=0.0,
            information=0.0,
            risk_tolerance=0.0,
        )
        for activity in StrategicActivity:
            for intent in (PRESSURE, STABILIZE, BUILD, indifferent):
                for opportunity, urgency, risk in itertools.product(
                    (0.0, 0.5, 1.0), repeat=3
                ):
                    evaluation = evaluate_mission(
                        MissionSignals(
                            activity=activity,
                            opportunity=opportunity,
                            urgency=urgency,
                            risk=risk,
                        ),
                        intent,
                    )
                    with self.subTest(
                        activity=activity.name,
                        opportunity=opportunity,
                        urgency=urgency,
                        risk=risk,
                    ):
                        if evaluation.viable:
                            self.assertGreater(evaluation.utility, 0.0)
                            self.assertGreaterEqual(
                                evaluation.priority, fallback + self.MARGIN
                            )
                        else:
                            self.assertEqual(evaluation.utility, 0.0)
                            self.assertIsNone(evaluation.priority)

    def test_the_viability_predicate_is_replaceable(self):
        signals = MissionSignals(
            activity=StrategicActivity.MAP_CONTROL, opportunity=0.2
        )

        default = evaluate_mission(signals, BUILD)
        strict = evaluate_mission(
            signals,
            BUILD,
            config=MissionPolicyConfig(minimum_viable_utility=default.utility),
        )

        self.assertTrue(default.viable)
        self.assertTrue(is_viable(default.utility))
        self.assertFalse(strict.viable)
        self.assertEqual(strict.reason, REJECTED_UTILITY_NOT_ABOVE_MINIMUM)
        self.assertFalse(is_viable(0.0))

    def test_a_priority_exists_exactly_when_viable(self):
        viable = evaluate_mission(good_harass(), BUILD)

        with self.assertRaises(ValueError):
            replace(viable, priority=None)
        with self.assertRaises(ValueError):
            replace(viable, viable=False)


class PriorityScaleTests(unittest.TestCase):
    def test_utility_maps_monotonically_onto_the_engine_scale(self):
        priorities = [to_priority(value / 10) for value in range(1, 11)]

        self.assertEqual(priorities, sorted(priorities))
        self.assertGreaterEqual(priorities[0], MissionPolicyConfig().minimum_priority)
        self.assertEqual(priorities[-1], 100)
        self.assertTrue(all(isinstance(value, int) for value in priorities))

    def test_a_non_viable_utility_has_no_priority(self):
        with self.assertRaises(ValueError):
            to_priority(0.0)

    def test_the_scale_rejects_an_inverted_configuration(self):
        with self.assertRaises(ValueError):
            MissionPolicyConfig(fallback_priority=40, minimum_priority=30)
        with self.assertRaises(ValueError):
            MissionPolicyConfig(emergency_urgency=1.0)
        with self.assertRaises(ValueError):
            MissionPolicyConfig(minimum_viable_utility=1.0)


if __name__ == "__main__":
    unittest.main()

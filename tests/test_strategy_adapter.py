from __future__ import annotations

import unittest
from dataclasses import replace

from sc2.position import Point2

from bot.app.strategy_runtime import StrategyRuntime
from bot.app.strategy_shadow import StrategyShadow
from bot.strategy import (
    MacroPosture,
    MacroPostureConfig,
    MacroPostureDirector,
    StrategicDirector,
    StrategicObjective,
    StrategyConfig,
    build_strategy_inputs,
    derive_intent,
)
from bot.world.awareness import (
    AwarenessSnapshot,
    BaseAssessment,
    BaseAwareness,
    BaseSecurityLevel,
    EnemyAwareness,
    RelativeStrength,
    ThreatAssessment,
)
from bot.world.awareness.territory import (
    TerritoryReading,
    TerritorySample,
    TerritorySnapshot,
)
from tests.fakes import FakeLogger


def snapshot(
    *,
    military_advantage: float = 0.5,
    military_confidence: float = 0.0,
    economic_advantage: float = 0.5,
    economic_confidence: float = 0.0,
    territory_dominance: float = 0.0,
    territory_confidence: float = 0.0,
    near_base_combat: int = 0,
    base_security: BaseSecurityLevel = BaseSecurityLevel.SAFE,
) -> AwarenessSnapshot:
    result = AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, 6, 0),
        threat=ThreatAssessment(
            visible_enemy_units=near_base_combat,
            known_anti_air_units=0,
            visible_anti_air_units=0,
            visible_enemy_combat_units=near_base_combat,
            near_own_base_enemy_units=near_base_combat,
            near_own_base_enemy_combat_units=near_base_combat,
        ),
        updated_at=100.0,
    )
    result = replace(
        result,
        army=replace(
            result.army,
            relative=replace(
                result.army.relative,
                advantage=military_advantage,
                confidence=military_confidence,
            ),
        ),
        economy=replace(
            result.economy,
            own_workers=30,
            own_bases=1,
            relative=replace(
                result.economy.relative,
                advantage=economic_advantage,
                confidence=economic_confidence,
            ),
        ),
        territory=TerritorySnapshot(
            confidence=territory_confidence,
            samples=(
                TerritorySample(
                    Point2((50, 50)),
                    TerritoryReading(
                        dominance=territory_dominance,
                        confidence=territory_confidence,
                    ),
                ),
            ),
        ),
    )
    if base_security is not BaseSecurityLevel.SAFE:
        result = replace(
            result,
            bases=BaseAwareness(
                (
                    BaseAssessment(
                        base_id="main",
                        position=Point2((10, 10)),
                        is_main=True,
                        threat_score=1.0,
                        protection_score=(
                            0.0
                            if base_security is BaseSecurityLevel.CRITICAL
                            else 1.0
                        ),
                        security=base_security,
                    ),
                )
            ),
        )
    return result


class AwarenessAdapterTests(unittest.TestCase):
    def test_maps_edges_threat_territory_and_confidence(self):
        awareness = snapshot(
            military_advantage=0.8,
            military_confidence=0.5,
            economic_advantage=0.25,
            economic_confidence=0.8,
            territory_dominance=0.6,
            territory_confidence=0.5,
            near_base_combat=3,
        )

        inputs = build_strategy_inputs(awareness)

        self.assertAlmostEqual(inputs.military_edge, 0.3)
        self.assertAlmostEqual(inputs.economic_edge, -0.4)
        self.assertAlmostEqual(inputs.territory_edge, 0.3)
        self.assertEqual(inputs.immediate_threat, 1.0)
        self.assertAlmostEqual(inputs.knowledge_confidence, 0.6)

    def test_low_knowledge_cannot_turn_an_assumed_edge_into_certainty(self):
        inputs = build_strategy_inputs(
            snapshot(
                military_advantage=1.0,
                military_confidence=0.0,
                economic_advantage=1.0,
                economic_confidence=0.0,
                territory_dominance=1.0,
                territory_confidence=0.0,
            )
        )

        self.assertEqual(inputs.military_edge, 0.0)
        self.assertEqual(inputs.economic_edge, 0.0)
        self.assertEqual(inputs.territory_edge, 0.0)
        self.assertEqual(inputs.knowledge_confidence, 0.0)

    def test_critical_base_threat_selects_stabilize_and_suppresses_ambition(self):
        inputs = build_strategy_inputs(
            snapshot(
                military_advantage=0.9,
                military_confidence=1.0,
                economic_advantage=0.8,
                economic_confidence=1.0,
                territory_dominance=0.6,
                territory_confidence=1.0,
                near_base_combat=1,
                base_security=BaseSecurityLevel.CRITICAL,
            )
        )
        result = StrategicDirector().update(inputs, 100.0)

        self.assertIs(result.objective, StrategicObjective.STABILIZE)
        self.assertGreater(
            result.score(StrategicObjective.STABILIZE),
            result.score(StrategicObjective.BUILD_ADVANTAGE),
        )
        self.assertGreater(
            result.score(StrategicObjective.STABILIZE),
            result.score(StrategicObjective.PRESSURE),
        )

    def test_military_deficit_contributes_to_recovery(self):
        inputs = build_strategy_inputs(
            snapshot(
                military_advantage=0.0,
                military_confidence=1.0,
                economic_advantage=0.2,
                economic_confidence=1.0,
                territory_confidence=1.0,
            )
        )
        result = StrategicDirector(
            replace(StrategyConfig(), minimum_dwell_seconds=0.0)
        ).update(inputs, 100.0)

        recovery = result.assessment(StrategicObjective.RECOVER)
        self.assertGreater(recovery.contribution("military_edge"), 0.0)
        self.assertIs(result.objective, StrategicObjective.RECOVER)


class StrategyRuntimeTests(unittest.TestCase):
    def test_runtime_logs_the_objective_and_publishes_its_intent(self):
        logger = FakeLogger()
        runner = StrategyRuntime(logger=logger)
        awareness = snapshot(near_base_combat=1)

        compatible = runner.update(awareness)

        self.assertIsNotNone(runner.snapshot)
        self.assertEqual(runner.context.intent, derive_intent(runner.snapshot))
        self.assertEqual(runner.context.updated_at, awareness.updated_at)
        self.assertIs(compatible.macro_posture, MacroPosture.DEFENSE)
        self.assertIs(awareness.macro_posture, MacroPosture.BALANCED)
        event = logger.events[0]
        self.assertEqual(event["name"], "strategy.updated")
        self.assertEqual(event["data"]["mode"], "live")
        self.assertFalse(event["data"]["shadow"])
        self.assertIn("scores", event["data"])

    def test_the_context_is_neutral_before_the_first_update(self):
        self.assertEqual(
            StrategyRuntime(logger=FakeLogger()).context.intent, derive_intent(None)
        )

    def test_the_deprecated_shadow_name_is_the_runtime(self):
        self.assertIs(StrategyShadow, StrategyRuntime)

    def test_legacy_posture_policy_keeps_its_defense_release_hysteresis(self):
        director = MacroPostureDirector(
            MacroPostureConfig(
                defense_release_after=10.0,
                greed_safe_after=20.0,
                minimum_hold_seconds=0.0,
            )
        )
        common = dict(
            workers=6,
            townhalls=0,
            own_combat=1,
            strength_is_stably_ahead=False,
        )

        danger = director.update(now=30.0, nearby_enemy_combat=1, **common)
        held = director.update(now=35.0, nearby_enemy_combat=0, **common)
        released = director.update(now=41.0, nearby_enemy_combat=0, **common)

        self.assertIs(danger, MacroPosture.DEFENSE)
        self.assertIs(held, MacroPosture.DEFENSE)
        self.assertIs(released, MacroPosture.RECOVERY)


if __name__ == "__main__":
    unittest.main()

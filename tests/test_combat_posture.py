from __future__ import annotations

import unittest

from sc2.position import Point2

from bot.behavior.army import CombatPosture, derive_combat_posture
from bot.world.awareness import (
    AwarenessSnapshot,
    MacroPosture,
    RelativeStrength,
    ThreatAssessment,
)
from bot.world.awareness.bases import BaseAssessment, BaseAwareness, BaseSecurityLevel
from bot.world.awareness.enemy import EnemyAwareness


def snapshot(
    *,
    score: float = 0.0,
    confidence: float = 0.6,
    macro_posture: MacroPosture = MacroPosture.BALANCED,
    threatened: bool = False,
    near_own_base_enemy_combat_units: int = 0,
) -> AwarenessSnapshot:
    base = BaseAssessment(
        base_id="base:1",
        position=Point2((10, 10)),
        is_main=True,
        threat_score=1.0 if threatened else 0.0,
        protection_score=0.0,
        security=(
            BaseSecurityLevel.CRITICAL if threatened else BaseSecurityLevel.SAFE
        ),
    )
    return AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(
            score=score,
            confidence=confidence,
            own_combat_units=0,
            known_enemy_combat_units=0,
        ),
        threat=ThreatAssessment(
            visible_enemy_units=0,
            known_anti_air_units=0,
            visible_anti_air_units=0,
            near_own_base_enemy_combat_units=near_own_base_enemy_combat_units,
        ),
        updated_at=0.0,
        macro_posture=macro_posture,
        bases=BaseAwareness((base,)),
    )


class CombatPostureTests(unittest.TestCase):
    def test_defaults_to_balanced_with_no_strong_signal(self):
        self.assertEqual(
            derive_combat_posture(awareness=snapshot()), CombatPosture.BALANCED
        )

    def test_turtles_when_a_base_is_threatened(self):
        self.assertEqual(
            derive_combat_posture(awareness=snapshot(threatened=True)),
            CombatPosture.TURTLE,
        )

    def test_turtles_when_macro_posture_is_defense_or_recovery(self):
        for macro in (MacroPosture.DEFENSE, MacroPosture.RECOVERY):
            with self.subTest(macro=macro):
                self.assertEqual(
                    derive_combat_posture(awareness=snapshot(macro_posture=macro)),
                    CombatPosture.TURTLE,
                )

    def test_turtles_when_confidently_behind(self):
        self.assertEqual(
            derive_combat_posture(
                awareness=snapshot(score=-0.5, confidence=0.7)
            ),
            CombatPosture.TURTLE,
        )

    def test_does_not_turtle_from_a_bad_score_with_no_confidence(self):
        # No confidence means no real evidence of being behind yet -- an
        # early-game score of exactly 0 with zero sightings should not
        # trigger a turtle posture.
        self.assertEqual(
            derive_combat_posture(awareness=snapshot(score=-0.5, confidence=0.0)),
            CombatPosture.BALANCED,
        )

    def test_pressures_when_confidently_ahead_and_safe(self):
        self.assertEqual(
            derive_combat_posture(
                awareness=snapshot(score=0.5, confidence=0.8)
            ),
            CombatPosture.PRESSURE,
        )

    def test_does_not_pressure_with_enemy_combat_units_near_home(self):
        self.assertEqual(
            derive_combat_posture(
                awareness=snapshot(
                    score=0.5,
                    confidence=0.8,
                    near_own_base_enemy_combat_units=1,
                )
            ),
            CombatPosture.BALANCED,
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from sc2.position import Point2

from bot.behavior.standing import CombatPosture, derive_combat_posture
from bot.world.awareness import (
    ArmyBelief,
    ArmySupplyEstimate,
    AwarenessSnapshot,
    EnemyArmyKnowledge,
    MacroPosture,
    RelativeAssessment,
    RelativePosition,
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
    position = (
        RelativePosition.AHEAD
        if score >= 0.15
        else RelativePosition.BEHIND
        if score <= -0.15
        else RelativePosition.EVEN
    )
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
        army=ArmyBelief(
            own_supply=0.0,
            enemy=EnemyArmyKnowledge(
                supply=ArmySupplyEstimate(0.0, 0.0, confidence),
                composition=(),
            ),
            relative=RelativeAssessment(position, position, confidence),
        ),
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

    def test_does_not_turtle_while_the_army_belief_reads_even(self):
        # An unscouted enemy reads EVEN: the belief itself carries the doubt.
        self.assertEqual(
            derive_combat_posture(awareness=snapshot(score=0.0, confidence=0.0)),
            CombatPosture.BALANCED,
        )

    def test_a_believed_position_is_not_second_guessed_by_its_confidence(self):
        # Gating the stable state on a separately decaying confidence is
        # what made the posture flip every time a scout lost vision.
        for score, expected in (
            (-0.5, CombatPosture.TURTLE),
            (0.5, CombatPosture.PRESSURE),
        ):
            with self.subTest(score=score):
                self.assertEqual(
                    derive_combat_posture(
                        awareness=snapshot(score=score, confidence=0.05)
                    ),
                    expected,
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

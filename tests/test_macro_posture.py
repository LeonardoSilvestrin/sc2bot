"""Macro's posture is macro's policy: derived by its own director, handed to
the planner as an explicit context, and logged as a macro decision -- never
carried by Awareness."""

from __future__ import annotations

import unittest
from dataclasses import replace

from bot.app.macro_context import MacroContextRuntime
from bot.macro import (
    MacroContext,
    MacroPosture,
    MacroPostureConfig,
    MacroPostureDirector,
)
from bot.world.awareness import AwarenessSnapshot, RelativeStrength, ThreatAssessment
from bot.world.awareness.enemy import EnemyAwareness
from tests.fakes import FakeLogger


def awareness(
    now: float, *, workers: int = 30, bases: int = 2, nearby: int = 0
) -> AwarenessSnapshot:
    snapshot = AwarenessSnapshot(
        enemy=EnemyAwareness(sightings=(), locations=()),
        relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
        threat=ThreatAssessment(0, 0, 0, near_own_base_enemy_combat_units=nearby),
        updated_at=now,
    )
    return replace(
        snapshot,
        economy=replace(snapshot.economy, own_workers=workers, own_bases=bases),
    )


class MacroPostureDirectorTests(unittest.TestCase):
    def test_defense_holds_through_its_release_window_then_releases(self):
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
        danger_reason = director.state.reason
        held = director.update(now=35.0, nearby_enemy_combat=0, **common)
        held_reason = director.state.reason
        released = director.update(now=41.0, nearby_enemy_combat=0, **common)

        self.assertIs(danger, MacroPosture.DEFENSE)
        self.assertEqual(danger_reason, "enemy_combat_near_base")
        self.assertIs(held, MacroPosture.DEFENSE)
        self.assertEqual(held_reason, "base_threat_within_release_window")
        self.assertIs(released, MacroPosture.RECOVERY)
        self.assertEqual(director.state.reason, "no_townhall_or_too_few_workers")

    def test_a_non_urgent_change_waits_the_minimum_hold(self):
        director = MacroPostureDirector(
            MacroPostureConfig(
                defense_release_after=0.0,
                greed_safe_after=0.0,
                minimum_hold_seconds=8.0,
            )
        )
        common = dict(workers=30, townhalls=2, own_combat=10, nearby_enemy_combat=0)

        greed = director.update(now=100.0, strength_is_stably_ahead=True, **common)
        held = director.update(now=103.0, strength_is_stably_ahead=False, **common)
        held_reason = director.state.reason
        balanced = director.update(now=109.0, strength_is_stably_ahead=False, **common)

        self.assertIs(greed, MacroPosture.GREED)
        self.assertIs(held, MacroPosture.GREED)
        self.assertEqual(held_reason, "minimum_hold_keeps_greed")
        self.assertIs(balanced, MacroPosture.BALANCED)


class MacroContextRuntimeTests(unittest.TestCase):
    def test_the_posture_reaches_macro_as_a_context_and_changes_are_logged(self):
        logger = FakeLogger()
        runtime = MacroContextRuntime(logger=logger)

        calm = runtime.update(awareness(100.0))
        runtime.update(awareness(101.0))
        attacked = runtime.update(awareness(102.0, nearby=3))

        self.assertEqual(calm, MacroContext(posture=MacroPosture.BALANCED))
        self.assertIs(attacked.posture, MacroPosture.DEFENSE)
        changes = [
            event["data"]
            for event in logger.events
            if event["name"] == "macro.posture"
        ]
        self.assertEqual(
            [change["posture"] for change in changes], ["BALANCED", "DEFENSE"]
        )
        self.assertEqual(changes[1]["previous_posture"], "BALANCED")
        self.assertEqual(changes[1]["reason"], "enemy_combat_near_base")
        self.assertEqual(changes[1]["inputs"]["near_own_base_enemy_combat_units"], 3)

    def test_awareness_is_never_written_to(self):
        state = awareness(100.0, nearby=3)

        MacroContextRuntime(logger=FakeLogger()).update(state)

        self.assertEqual(state, awareness(100.0, nearby=3))
        self.assertFalse(hasattr(state, "macro_posture"))


if __name__ == "__main__":
    unittest.main()

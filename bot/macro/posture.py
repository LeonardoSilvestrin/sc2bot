"""Macro posture: how much risk spending takes right now.

A macro policy, owned by macro. ``MacroPostureDirector`` derives it from what
Awareness describes -- enemy force near our bases, workers, townhalls, the
army belief -- with hysteresis. ``bot.app`` runs the director every frame and
hands ``MacroPlanner`` the result as an explicit ``MacroContext``. It never
travels through Awareness, which only describes.

The rules are the legacy ones, carried over unchanged until a mathematical
macro model replaces them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class MacroPosture(Enum):
    """How risky spending is right now.

    DEFENSE   enemy combat units are at our bases, or were moments ago
    BALANCED  the default
    GREED     safe for a while and stably ahead
    RECOVERY  no townhall, or too few workers past the opening
    """

    DEFENSE = auto()
    BALANCED = auto()
    GREED = auto()
    RECOVERY = auto()


@dataclass(frozen=True, slots=True)
class MacroContext:
    """The macro policy ``MacroPlanner`` is handed each frame, beyond Attention
    and Awareness."""

    posture: MacroPosture = MacroPosture.BALANCED

    def log_fields(self) -> dict[str, Any]:
        return {"posture": self.posture.name}


@dataclass(frozen=True, slots=True)
class MacroPostureConfig:
    """Timings of the posture policy."""

    defense_release_after: float = 10.0
    greed_safe_after: float = 20.0
    minimum_hold_seconds: float = 8.0

    def __post_init__(self) -> None:
        if min(
            self.defense_release_after,
            self.greed_safe_after,
            self.minimum_hold_seconds,
        ) < 0.0:
            raise ValueError("posture timings must not be negative")


@dataclass(frozen=True, slots=True)
class MacroPostureState:
    """The posture in force, its hysteresis clocks, and why it holds."""

    posture: MacroPosture = MacroPosture.BALANCED
    changed_at: float = float("-inf")
    last_base_threat_at: float = float("-inf")
    reason: str = "initial_balanced"


class MacroPostureDirector:
    """The posture rules, with hysteresis.

    An enemy force at our bases or a ruined economy switches at once; any
    other change waits ``minimum_hold_seconds`` after the last one. Each
    update records a machine-readable reason in ``state``.
    """

    def __init__(self, config: MacroPostureConfig | None = None) -> None:
        self.config = config or MacroPostureConfig()
        self._state = MacroPostureState()

    @property
    def state(self) -> MacroPostureState:
        return self._state

    @property
    def posture(self) -> MacroPosture:
        return self._state.posture

    def update(
        self,
        *,
        now: float,
        workers: int,
        townhalls: int,
        own_combat: int,
        strength_is_stably_ahead: bool,
        nearby_enemy_combat: int,
    ) -> MacroPosture:
        state = self._state
        last_threat = state.last_base_threat_at
        if nearby_enemy_combat:
            candidate, reason = MacroPosture.DEFENSE, "enemy_combat_near_base"
            last_threat = now
        elif now - last_threat < self.config.defense_release_after:
            candidate = MacroPosture.DEFENSE
            reason = "base_threat_within_release_window"
        elif townhalls == 0 or (now >= 90.0 and workers < 8):
            candidate, reason = MacroPosture.RECOVERY, "no_townhall_or_too_few_workers"
        elif (
            now - last_threat >= self.config.greed_safe_after
            and strength_is_stably_ahead
            and own_combat >= 6
        ):
            candidate, reason = MacroPosture.GREED, "safe_and_stably_ahead"
        else:
            candidate, reason = MacroPosture.BALANCED, "no_special_condition"

        immediate = candidate in {MacroPosture.DEFENSE, MacroPosture.RECOVERY}
        posture = state.posture
        changed_at = state.changed_at
        if candidate is not posture:
            if immediate or now - changed_at >= self.config.minimum_hold_seconds:
                posture = candidate
                changed_at = now
            else:
                reason = f"minimum_hold_keeps_{posture.name.lower()}"
        self._state = MacroPostureState(
            posture=posture,
            changed_at=changed_at,
            last_base_threat_at=last_threat,
            reason=reason,
        )
        return posture


__all__ = [
    "MacroContext",
    "MacroPosture",
    "MacroPostureConfig",
    "MacroPostureDirector",
    "MacroPostureState",
]

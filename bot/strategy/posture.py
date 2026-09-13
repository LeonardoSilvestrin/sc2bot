from __future__ import annotations

from dataclasses import dataclass

from bot.domain.posture import MacroPosture


@dataclass(frozen=True, slots=True)
class MacroPostureConfig:
    """Compatibility policy timings for current behavior and macro callers."""

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
    """Hysteresis state for the legacy strategic posture."""

    posture: MacroPosture = MacroPosture.BALANCED
    changed_at: float = float("-inf")
    last_base_threat_at: float = float("-inf")


class MacroPostureDirector:
    """Own the old posture policy while the new director runs in shadow mode.

    This preserves the decisions existing consumers already receive.  It is
    intentionally separate from ``StrategicDirector`` so shadow observations
    cannot change gameplay before their scores have been validated.
    """

    def __init__(self, config: MacroPostureConfig | None = None) -> None:
        self.config = config or MacroPostureConfig()
        self._state = MacroPostureState()

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
            candidate = MacroPosture.DEFENSE
            last_threat = now
        elif now - last_threat < self.config.defense_release_after:
            candidate = MacroPosture.DEFENSE
        elif townhalls == 0 or (now >= 90.0 and workers < 8):
            candidate = MacroPosture.RECOVERY
        elif (
            now - last_threat >= self.config.greed_safe_after
            and strength_is_stably_ahead
            and own_combat >= 6
        ):
            candidate = MacroPosture.GREED
        else:
            candidate = MacroPosture.BALANCED

        immediate = candidate in {MacroPosture.DEFENSE, MacroPosture.RECOVERY}
        posture = state.posture
        changed_at = state.changed_at
        if candidate is not posture and (
            immediate or now - changed_at >= self.config.minimum_hold_seconds
        ):
            posture = candidate
            changed_at = now
        self._state = MacroPostureState(
            posture=posture,
            changed_at=changed_at,
            last_base_threat_at=last_threat,
        )
        return posture


__all__ = [
    "MacroPosture",
    "MacroPostureConfig",
    "MacroPostureDirector",
    "MacroPostureState",
]

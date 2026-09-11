from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class MacroPosture(Enum):
    """Coarse strategic pressure used to arbitrate economic spending.

    The posture describes how risky spending is right now; ``bot.macro``
    still owns what the bot is trying to build. Behaviors read it too, as a
    coarse risk signal (standing, map control).
    """

    DEFENSE = auto()
    BALANCED = auto()
    GREED = auto()
    RECOVERY = auto()


@dataclass(frozen=True, slots=True)
class PostureState:
    """Hysteresis bookkeeping ``derive_macro_posture`` needs across ticks."""

    posture: MacroPosture = MacroPosture.BALANCED
    posture_changed_at: float = float("-inf")
    last_base_threat_at: float = float("-inf")


def derive_macro_posture(
    *,
    now: float,
    workers: int,
    townhalls: int,
    own_combat: int,
    strength_score: float,
    strength_confidence: float,
    strength_is_stably_ahead: bool,
    nearby_enemy_combat: int,
    state: PostureState,
    defense_release_after: float,
    greed_safe_after: float,
    posture_min_hold: float,
) -> PostureState:
    """Apply immediate danger and slow release/greed hysteresis.

    This is strategy/policy, not observation: it decides how risky spending
    is right now, not what is true about the world. ``AwarenessService``
    holds the resulting posture (and this state) between ticks; the decision
    itself lives here so it can be reasoned about and tested independently.
    """

    last_base_threat_at = state.last_base_threat_at
    if nearby_enemy_combat:
        candidate = MacroPosture.DEFENSE
        last_base_threat_at = now
    elif now - last_base_threat_at < defense_release_after:
        candidate = MacroPosture.DEFENSE
    elif townhalls == 0 or (now >= 90.0 and workers < 8):
        candidate = MacroPosture.RECOVERY
    elif (
        now - last_base_threat_at >= greed_safe_after
        and strength_is_stably_ahead
        and strength_confidence >= 0.5
        and own_combat >= 6
        and strength_score >= 0.25
    ):
        candidate = MacroPosture.GREED
    else:
        candidate = MacroPosture.BALANCED

    immediate = candidate in {MacroPosture.DEFENSE, MacroPosture.RECOVERY}
    posture = state.posture
    posture_changed_at = state.posture_changed_at
    if candidate is not posture and (
        immediate or now - posture_changed_at >= posture_min_hold
    ):
        posture = candidate
        posture_changed_at = now

    return PostureState(
        posture=posture,
        posture_changed_at=posture_changed_at,
        last_base_threat_at=last_base_threat_at,
    )

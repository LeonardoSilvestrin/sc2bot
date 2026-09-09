from __future__ import annotations

from enum import Enum, auto

from bot.world.awareness import AwarenessSnapshot, MacroPosture


class CombatPosture(Enum):
    """How defensively the standing army should currently be arranged.

    This is deliberately a different axis from ``MacroPosture``:
    ``MacroPosture`` is economic/strategic policy (how risky spending is
    right now); ``CombatPosture`` is only about where standing military
    force should sit when nothing more urgent (``DEFENSE``, ``HARASS``, ...)
    needs it. Mixing the two would conflate "should I greed for a fourth
    base" with "should my army be forward or home", which are genuinely
    different questions answered from different evidence.
    """

    TURTLE = auto()
    BALANCED = auto()
    PRESSURE = auto()


def derive_combat_posture(*, awareness: AwarenessSnapshot) -> CombatPosture:
    """A small, deterministic policy over already-computed Awareness signals.

    No new observation is introduced here -- ``bases.threatened``,
    ``relative_strength`` and ``macro_posture`` already exist precisely to
    answer "is something wrong right now" and "are we ahead". This pilot
    only has to decide which of three postures that maps to.
    """

    strength = awareness.relative_strength
    if (
        awareness.bases.threatened
        or awareness.macro_posture in {MacroPosture.DEFENSE, MacroPosture.RECOVERY}
        or (strength.confidence > 0.0 and strength.score <= -0.25)
    ):
        return CombatPosture.TURTLE

    if (
        strength.confidence >= 0.5
        and strength.score >= 0.35
        and awareness.threat.near_own_base_enemy_combat_units == 0
    ):
        return CombatPosture.PRESSURE

    return CombatPosture.BALANCED

"""What Strategy hands the behavior layer each frame."""

from __future__ import annotations

from dataclasses import dataclass

from .intent import StrategicIntent, derive_intent
from .mission_policy import ControlNeed


@dataclass(frozen=True, slots=True)
class StrategicContext:
    """Strategy's current prescriptions, read-only, for planners and ranking.

    It deliberately carries the intent and not the ``StrategicObjective``:
    behaviors read one smooth vocabulary and never reinterpret the objective.
    ``updated_at`` is the game time Strategy last recomputed it.
    """

    intent: StrategicIntent
    updated_at: float = 0.0

    @classmethod
    def neutral(cls) -> StrategicContext:
        """The context before Strategy has run: the fallback objective's intent."""

        return cls(intent=derive_intent(None))

    def need_for(self, objective_id: str | None) -> ControlNeed | None:
        """What the named control objective still asks for; ``None`` if unknown."""

        return None


__all__ = ["StrategicContext"]

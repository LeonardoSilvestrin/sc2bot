"""What Strategy hands the behavior layer each frame."""

from __future__ import annotations

from dataclasses import dataclass, field

from .intent import StrategicIntent, derive_intent
from .mission_policy import ControlNeed
from .spatial.model import SpatialStrategySnapshot


@dataclass(frozen=True, slots=True)
class StrategicContext:
    """Strategy's current prescriptions, read-only, for planners and ranking.

    - ``intent``: how much each activity is wanted.
    - ``spatial``: where control is wanted (``ControlObjective``\\ s).
    - ``updated_at``: the game time Strategy last recomputed them.

    It deliberately carries no ``StrategicObjective``: behaviors read one
    smooth vocabulary and never reinterpret the objective.
    """

    intent: StrategicIntent
    spatial: SpatialStrategySnapshot = field(default_factory=SpatialStrategySnapshot)
    updated_at: float = 0.0

    @classmethod
    def neutral(cls) -> StrategicContext:
        """The context before Strategy has run: the fallback objective's
        intent and no spatial objective."""

        return cls(intent=derive_intent(None))

    def need_for(self, objective_id: str | None) -> ControlNeed | None:
        """What the named control objective still asks for; ``None`` if unknown."""

        if objective_id is None:
            return None
        objective = self.spatial.get(objective_id)
        return None if objective is None else objective.need


__all__ = ["StrategicContext"]

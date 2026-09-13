"""Types of Strategy's spatial prescriptions: where control is wanted."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from sc2.position import Point2

from ..intent import StrategicActivity
from ..mission_policy import ControlNeed

_UNIT_FIELDS = (
    "desired_control",
    "desired_visibility",
    "importance",
    "current_control",
    "current_visibility",
)


class ControlTargetKind(Enum):
    """What a control objective is about.

    BASE      one of our held bases
    REGION    a ground region from the map's region graph
    PASSAGE   a ground connection between two regions
    AREA      a place with no region of its own (reserved)
    """

    BASE = auto()
    REGION = auto()
    PASSAGE = auto()
    AREA = auto()


@dataclass(frozen=True, slots=True)
class ControlObjective:
    """A world state Strategy wants, and how far the world is from it.

    Not a mission: it names no unit, count, formation or priority. Behaviors
    decide how to satisfy it; the Mission Policy weighs how much serving it
    is worth.

    - ``desired_control``, ``desired_visibility``: 0..1, how firmly Strategy
      wants the place held and watched. Strategy's values; Awareness never
      carries them.
    - ``importance``: 0..1, how much the objective matters against the others.
    - ``current_control``, ``current_visibility``: 0..1, Awareness' reading of
      the place when the objective was derived (a base's ground security, a
      passage's hold, a region's dominance; their confidence). Copied for the
      gap and for diagnostics, never written back.
    - ``protects``: for a passage, the id of the base objective it guards.
    """

    objective_id: str
    kind: ControlTargetKind
    target_key: str
    position: Point2
    activity: StrategicActivity
    desired_control: float
    desired_visibility: float
    importance: float
    current_control: float
    current_visibility: float
    reason: str
    region_key: str | None = None
    protects: str | None = None

    def __post_init__(self) -> None:
        for name in _UNIT_FIELDS:
            value = getattr(self, name)
            # NaN fails this comparison too.
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1], got {value}")
        if not self.objective_id.strip() or not self.target_key.strip():
            raise ValueError("objective_id and target_key must not be blank")

    @property
    def control_gap(self) -> float:
        return max(0.0, self.desired_control - self.current_control)

    @property
    def visibility_gap(self) -> float:
        return max(0.0, self.desired_visibility - self.current_visibility)

    @property
    def gap(self) -> float:
        """The larger shortfall, control or visibility."""

        return max(self.control_gap, self.visibility_gap)

    @property
    def need(self) -> ControlNeed:
        return ControlNeed(importance=self.importance, gap=self.gap)

    def log_fields(self) -> dict[str, Any]:
        return {
            "id": self.objective_id,
            "kind": self.kind.name,
            "target": self.target_key,
            "position": [
                round(float(self.position.x), 1),
                round(float(self.position.y), 1),
            ],
            "activity": self.activity.name,
            "importance": round(self.importance, 3),
            "desired_control": round(self.desired_control, 3),
            "current_control": round(self.current_control, 3),
            "control_gap": round(self.control_gap, 3),
            "desired_visibility": round(self.desired_visibility, 3),
            "current_visibility": round(self.current_visibility, 3),
            "visibility_gap": round(self.visibility_gap, 3),
            "region": self.region_key,
            "protects": self.protects,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class SpatialStrategySnapshot:
    """Every control objective Strategy holds, most important first."""

    objectives: tuple[ControlObjective, ...] = field(default_factory=tuple)
    updated_at: float = 0.0

    def get(self, objective_id: str) -> ControlObjective | None:
        return next(
            (item for item in self.objectives if item.objective_id == objective_id),
            None,
        )

    def of_kind(self, *kinds: ControlTargetKind) -> tuple[ControlObjective, ...]:
        return tuple(item for item in self.objectives if item.kind in kinds)

    def protecting(self, objective_id: str) -> tuple[ControlObjective, ...]:
        """The objectives guarding ``objective_id``, most important first."""

        return tuple(item for item in self.objectives if item.protects == objective_id)


__all__ = ["ControlObjective", "ControlTargetKind", "SpatialStrategySnapshot"]

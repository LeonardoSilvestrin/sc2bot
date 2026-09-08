from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from sc2.position import Point2


class BaseSecurityLevel(Enum):
    """How safe one held base currently is, from no threat to undefended.

    Protection never fully suppresses a proposal here -- a nearby own unit
    may already be committed to another mission, and only the allocator's
    priority/preemption knows that (see ``DefensePlanner``). Protection only
    affects severity (CRITICAL vs THREATENED) and how many units get asked
    for.
    """

    SAFE = auto()
    THREATENED = auto()
    CRITICAL = auto()


@dataclass(frozen=True, slots=True)
class BaseAssessment:
    """Threat vs protection reading for one held base.

    ``threat_score`` and ``protection_score`` are simple weighted counts for
    now (see ``BaseSecurityAssessor``); the shape is stable so a future,
    more accurate scoring (e.g. combat-sim based) can replace the numbers
    without changing callers.
    """

    base_id: str
    position: Point2
    is_main: bool
    threat_score: float
    protection_score: float
    security: BaseSecurityLevel
    nearest_threat_position: Point2 | None = None

    @property
    def needs_defense(self) -> bool:
        return self.security is not BaseSecurityLevel.SAFE


@dataclass(frozen=True, slots=True)
class BaseAwareness:
    """Every currently held base with its security reading."""

    assessments: tuple[BaseAssessment, ...] = field(default_factory=tuple)

    def get(self, base_id: str) -> BaseAssessment | None:
        return next(
            (item for item in self.assessments if item.base_id == base_id), None
        )

    @property
    def threatened(self) -> tuple[BaseAssessment, ...]:
        return tuple(item for item in self.assessments if item.needs_defense)

    def __iter__(self):
        return iter(self.assessments)

    def __len__(self) -> int:
        return len(self.assessments)

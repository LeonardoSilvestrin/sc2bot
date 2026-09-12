from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from sc2.position import Point2

from .memory import EnemyBaseStatus


@dataclass(frozen=True, slots=True)
class EnemyBaseAssessment:
    """What one candidate enemy base slot is believed to be worth, and how
    well it is believed to be defended.

    Every reading keeps two things apart: what we believe existed, from the
    last information known, and how much that still describes the present.
    ``economic_value``, ``air_defense`` and ``ground_defense`` (0..1) are the
    former and never shrink with age. ``confidence`` -- how recently the slot
    itself was looked at -- backs ``status`` and ``economic_value``; each
    defense reading carries its own confidence, because defenders are seen
    apart from the slot and a unit goes stale far faster than a structure.
    Combining value with confidence is the reading behavior's call. How each
    number is computed lives in ``enemy/heuristics.py``.

    ``status``, ``last_confirmed_at``, ``last_checked_at``, ``confidence``
    and ``is_stale`` are the slot's ``EnemyBaseObservation``.
    """

    key: str
    position: Point2
    status: EnemyBaseStatus
    economic_value: float
    # The workers last counted here, and when (``None``: never counted).
    worker_count_estimate: int
    workers_counted_at: float | None
    air_defense: float
    # Value-weighted freshness of the defenders behind each defense reading;
    # with none seen, the slot's own ``confidence``.
    air_defense_confidence: float
    ground_defense: float
    ground_defense_confidence: float
    last_confirmed_at: float | None
    last_checked_at: float | None
    confidence: float
    is_stale: bool

    @property
    def is_confirmed(self) -> bool:
        return self.status is EnemyBaseStatus.CONFIRMED


@dataclass(frozen=True, slots=True)
class EnemyBaseAwareness:
    """Every candidate enemy base slot, with its assessment."""

    assessments: tuple[EnemyBaseAssessment, ...] = field(default_factory=tuple)

    def get(self, key: str) -> EnemyBaseAssessment | None:
        return next((item for item in self.assessments if item.key == key), None)

    @property
    def confirmed(self) -> tuple[EnemyBaseAssessment, ...]:
        return tuple(item for item in self.assessments if item.is_confirmed)

    def __iter__(self) -> Iterator[EnemyBaseAssessment]:
        return iter(self.assessments)

    def __len__(self) -> int:
        return len(self.assessments)

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

class ActionStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    BLOCKED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class ActionOutcome(Enum):
    RUNNING = auto()
    BLOCKED = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class ActionResult:
    outcome: ActionOutcome
    reason: str
    retry_after: float | None = None

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("ActionResult.reason must not be empty")

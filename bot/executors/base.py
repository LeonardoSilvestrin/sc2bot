from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto

from bot.attention.models import AttentionSnapshot, UnitSnapshot
from bot.awareness.models import AwarenessSnapshot
from bot.contracts.commands import MissionCommands


class MissionOutcome(Enum):
    ACTIVE = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class MissionResult:
    outcome: MissionOutcome
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("MissionResult.reason must not be empty")


@dataclass(frozen=True, slots=True)
class MissionContext:
    attention: AttentionSnapshot
    awareness: AwarenessSnapshot
    assigned_units: tuple[UnitSnapshot, ...]
    commands: MissionCommands


class MissionExecutor(ABC):
    @abstractmethod
    async def step(self, context: MissionContext) -> MissionResult:
        raise NotImplementedError

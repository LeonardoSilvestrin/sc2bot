from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from bot.engine.missions.models import Mission
from bot.ports.mission_commands import MissionCommands
from bot.world.attention import AttentionSnapshot, UnitSnapshot
from bot.world.awareness import AwarenessSnapshot


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


MissionExecutorFactory = Callable[[Mission, float], MissionExecutor]

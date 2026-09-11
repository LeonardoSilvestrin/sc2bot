from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from bot.engine.missions.models import Mission
from bot.engine.services import BehaviorServices
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
    services: BehaviorServices | None = None


class MissionExecutor(ABC):
    @abstractmethod
    async def step(self, context: MissionContext) -> MissionResult:
        raise NotImplementedError

    def refresh(self, mission: Mission) -> None:
        """Pick up a changed live proposal (target, config, ...) before `step`.

        A STANDING mission's proposal can be replaced in place while the
        same executor instance keeps running (see
        ``MissionController._update_standing``) -- most executors have
        nothing to resync, so this defaults to a no-op.
        """

        return None

    def preemption_cost(self) -> float:
        """Extra priority another mission must clear to take our units now.

        This is the executor's own tactical answer, not policy: only the
        thing actually running the mission knows that its Banshees are
        cloaked inside a worker line rather than still flying out. It is
        added to ``UnitAllocator.preemption_margin`` for this mission's
        leases (see ``UnitLease.preemption_cost``); returning 0.0 -- the
        default -- leaves arbitration purely priority-based.
        """

        return 0.0


MissionExecutorFactory = Callable[[Mission, float], MissionExecutor]

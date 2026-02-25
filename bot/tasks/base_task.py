# bot/tasks/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from bot.mind.attention import Attention


class TaskStatus(str, Enum):
    """
    Task lifecycle. Keep values stable because logs/debug will depend on this.
    """
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DONE = "DONE"
    ABORTED = "ABORTED"


@dataclass(frozen=True)
class TaskTick:
    iteration: int
    time: float


@dataclass(frozen=True)
class TaskResult:
    """
    Unified execution feedback (task -> Ego).
    Tasks SHOULD return this, but BaseTask supports legacy bool returns.

    status:
      - RUNNING: task continues as active mission
      - DONE: task completed successfully (mission can end)
      - FAILED: task failed (mission should end; Ego applies cooldown etc.)
      - NOOP: task chose to do nothing this tick (still running)
    """
    status: str  # RUNNING | DONE | FAILED | NOOP
    reason: str = ""
    retry_after_s: float = 0.0
    telemetry: Optional[dict] = None

    @staticmethod
    def running(reason: str = "", telemetry: Optional[dict] = None) -> "TaskResult":
        return TaskResult(status="RUNNING", reason=str(reason), telemetry=telemetry)

    @staticmethod
    def done(reason: str = "", telemetry: Optional[dict] = None) -> "TaskResult":
        return TaskResult(status="DONE", reason=str(reason), telemetry=telemetry)

    @staticmethod
    def failed(reason: str = "", retry_after_s: float = 8.0, telemetry: Optional[dict] = None) -> "TaskResult":
        return TaskResult(status="FAILED", reason=str(reason), retry_after_s=float(retry_after_s), telemetry=telemetry)

    @staticmethod
    def noop(reason: str = "", telemetry: Optional[dict] = None) -> "TaskResult":
        return TaskResult(status="NOOP", reason=str(reason), telemetry=telemetry)


@runtime_checkable
class Task(Protocol):
    """
    Contract required by Ego + planners.

    Notes:
    - domain is a string slot key (e.g. "DEFENSE", "INTEL")
    """
    task_id: str
    domain: str
    commitment: int  # how "expensive" / exclusive this task is (can be used later)

    def status(self) -> TaskStatus: ...
    def is_done(self) -> bool: ...

    def evaluate(self, bot, attention: Attention) -> int: ...

    async def step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult: ...

    async def pause(self, bot, reason: str) -> None: ...
    async def abort(self, bot, reason: str) -> None: ...


@dataclass
class BaseTask:
    """
    Convenience base class.

    You implement on_step(); everything else is standard.
    """
    task_id: str
    domain: str

    commitment: int = 1

    _status: TaskStatus = field(default=TaskStatus.IDLE, init=False)
    _last_reason: str = field(default="", init=False)
    _last_step_t: float = field(default=0.0, init=False)

    # -----------------------
    # Core contract
    # -----------------------
    def status(self) -> TaskStatus:
        return self._status

    def is_done(self) -> bool:
        return self._status in (TaskStatus.DONE, TaskStatus.ABORTED)

    def evaluate(self, bot, attention: Attention) -> int:
        """
        Optional: tasks can provide a default evaluation score.
        Most scoring should stay in planners; this hook is for quick heuristics/tests.
        """
        return 0

    async def step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        """
        Standard wrapper:
        - blocks stepping if DONE/ABORTED
        - ensures ACTIVE state when running
        - normalizes return type to TaskResult (supports legacy bool)
        """
        if self.is_done():
            return TaskResult.noop("already_done")

        if self._status == TaskStatus.IDLE:
            self._status = TaskStatus.ACTIVE

        self._last_step_t = float(tick.time)

        out: Any = await self.on_step(bot, tick, attention)

        # Normalize TaskResult
        if isinstance(out, TaskResult):
            return out

        # Legacy support: bool return
        if isinstance(out, bool):
            return TaskResult.running("did_any" if out else "idle")

        # Unknown return: treat as running but record
        return TaskResult.running("unknown_return_type")

    async def pause(self, bot, reason: str) -> None:
        if self.is_done():
            return
        self._status = TaskStatus.PAUSED
        self._last_reason = str(reason)

    async def abort(self, bot, reason: str) -> None:
        if self.is_done():
            return
        self._status = TaskStatus.ABORTED
        self._last_reason = str(reason)

    # -----------------------
    # To implement
    # -----------------------
    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult | bool:
        """
        Implement task logic.

        Preferred: return TaskResult.
        Legacy: return bool (True if issued commands).
        """
        raise NotImplementedError

    # -----------------------
    # Helpers (optional)
    # -----------------------
    def _done(self, reason: str = "") -> None:
        self._status = TaskStatus.DONE
        self._last_reason = str(reason)

    def _active(self, reason: str = "") -> None:
        self._status = TaskStatus.ACTIVE
        if reason:
            self._last_reason = str(reason)

    def _paused(self, reason: str = "") -> None:
        self._status = TaskStatus.PAUSED
        if reason:
            self._last_reason = str(reason)

    def last_reason(self) -> str:
        return self._last_reason

    def last_step_time(self) -> float:
        return float(self._last_step_t)
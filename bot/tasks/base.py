# bot/tasks/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Protocol, runtime_checkable

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


@runtime_checkable
class Task(Protocol):
    """
    Contract required by Ego + planners.

    Notes:
    - domain is a string slot key (e.g. "DEFENSE", "INTEL")
    - step() returns True if the task consumed 1 unit of command budget
    """
    task_id: str
    domain: str
    commitment: int  # how "expensive" / exclusive this task is (can be used later)

    def status(self) -> TaskStatus: ...
    def is_done(self) -> bool: ...

    def evaluate(self, bot, attention: Attention) -> int: ...
    async def step(self, bot, tick: TaskTick, attention: Attention) -> bool: ...

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
        Most of your scoring should stay in planners, but this hook is useful
        for quick heuristics and testing.
        """
        return 0

    async def step(self, bot, tick: TaskTick, attention: Attention) -> bool:
        """
        Standard wrapper: blocks stepping if DONE/ABORTED, and ensures
        ACTIVE state when running.
        """
        if self.is_done():
            return False

        # If task is paused, it still may run if Ego kept it active;
        # treat pause as a state that on_step can honor, but don't force-run.
        if self._status == TaskStatus.IDLE:
            self._status = TaskStatus.ACTIVE

        self._last_step_t = float(tick.time)
        used = await self.on_step(bot, tick, attention)

        # If task reached terminal status inside on_step, fine.
        # Otherwise keep it ACTIVE/PAUSED.
        return bool(used)

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
    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> bool:
        """
        Implement task logic.
        Return True if you issued commands and want to consume 1 budget unit.
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
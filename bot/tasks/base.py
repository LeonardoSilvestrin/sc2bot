from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from bot.mind.attention import Attention


class TaskStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DONE = "DONE"


@dataclass(frozen=True)
class TaskTick:
    iteration: int
    time: float


class Task(Protocol):
    task_id: str
    domain: str
    status: TaskStatus
    commitment: int

    def evaluate(self, bot, attention: Attention) -> int: ...
    async def step(self, bot, tick: TaskTick, attention: Attention) -> bool: ...

    async def pause(self, bot, reason: str) -> None: ...
    async def abort(self, bot, reason: str) -> None: ...
    def is_done(self) -> bool: ...
#bot/actions/base.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class TickContext:
    iteration: int
    time: float
    opening_done: bool
    threatened: bool


class Action(Protocol):
    name: str
    priority: int
    allow_during_opening: bool

    def is_done(self) -> bool: ...
    async def step(self, bot, ctx: TickContext) -> bool: ...
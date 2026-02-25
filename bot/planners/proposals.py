from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.tasks.base import Task


class Planner(Protocol):
    planner_id: str

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list["Proposal"]:
        ...


@dataclass(frozen=True)
class Proposal:
    domain: str
    score: int
    task: Task
    reason: Optional[str] = None
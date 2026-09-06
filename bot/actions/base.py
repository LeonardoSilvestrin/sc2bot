from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from bot.actions.models import ActionResult, ActionStatus
from bot.attention.models import AttentionSnapshot, UnitSnapshot
from bot.contracts.allocation import UnitRequirement
from bot.contracts.commands import ActionCommands
from bot.contracts.logging import BotLogger


@dataclass(frozen=True, slots=True)
class ActionContext:
    attention: AttentionSnapshot
    assigned_units: tuple[UnitSnapshot, ...]
    commands: ActionCommands
    logger: BotLogger


@dataclass
class Action(ABC):
    action_id: str
    priority: int
    status: ActionStatus = field(default=ActionStatus.PENDING, init=False)
    started_at: float | None = field(default=None, init=False)
    last_reason: str = field(default="created", init=False)

    @abstractmethod
    def requirements(self, attention: AttentionSnapshot) -> tuple[UnitRequirement, ...]:
        pass

    @abstractmethod
    async def step(self, context: ActionContext) -> ActionResult:
        pass

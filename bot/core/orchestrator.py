#bot/core/orchestrator.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from bot.actions.base import Action, TickContext


@dataclass
class Orchestrator:
    """
    MVP:
      - Agenda ações por prioridade.
      - Gating por opening (allow_during_opening).
      - Budget de comandos por tick.
      - Preempção simples em ameaça.
    """
    command_budget: int = 2
    defense_floor: int = 80  # se threatened, só roda ações >= isso

    actions: List[Action] = field(default_factory=list)

    def add(self, action: Action) -> None:
        self.actions.append(action)

    async def tick(self, bot, ctx: TickContext) -> None:
        runnable: List[Action] = []

        for a in self.actions:
            if a.is_done():
                continue
            if (not ctx.opening_done) and (not a.allow_during_opening):
                continue
            if ctx.threatened and a.priority < self.defense_floor:
                continue
            runnable.append(a)

        runnable.sort(key=lambda x: x.priority, reverse=True)

        budget = self.command_budget
        for a in runnable:
            if budget <= 0:
                break
            used = await a.step(bot, ctx)
            if used:
                budget -= 1
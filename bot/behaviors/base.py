# behaviors/base.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TickBudget:
    remaining: int = 1

    def spend(self, n: int = 1) -> bool:
        if self.remaining < n:
            return False
        self.remaining -= n
        return True


class Behavior:
    name: str = "behavior"

    def __init__(self, bot: Any, ctx: Any, logger: Any | None = None, debug: bool = True):
        self.bot = bot
        self.ctx = ctx
        self.log = logger
        self.debug = debug

    async def step(self, budget: TickBudget) -> bool:
        """
        Retorna True se emitiu alguma ação relevante (gastou budget).
        """
        return False
from __future__ import annotations

from typing import Any

from .base import TickBudget


class CombatBehavior:
    name = "combat"

    def __init__(self, bot: Any, ctx: Any, logger: Any | None = None, debug: bool = True):
        self.bot = bot
        self.ctx = ctx
        self.log = logger
        self.debug = debug

    async def step(self, budget: TickBudget, cfg: dict) -> bool:
        combat_cfg = cfg["combat"]
        if not combat_cfg.enabled:
            return False
        # ainda vazio
        return False
from __future__ import annotations

from typing import Any

from .base import TickBudget


class DropBehavior:
    name = "drop"

    def __init__(self, bot: Any, ctx: Any, logger: Any | None = None, debug: bool = True):
        self.bot = bot
        self.ctx = ctx
        self.log = logger
        self.debug = debug

    async def step(self, budget: TickBudget, cfg: dict) -> bool:
        # cfg esperado: {"drop": DropCfg}
        drop_cfg = cfg["drop"]
        if not drop_cfg.enabled:
            return False

        # por enquanto sem ações -> não gasta budget
        # quando você implementar unload/move/load etc, aí consome budget
        return False
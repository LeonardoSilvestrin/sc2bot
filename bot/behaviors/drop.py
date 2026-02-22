# behaviors/drop.py
from __future__ import annotations

from typing import Any

from bot.strategy.schema import DropCfg


class DropBehavior:
    def __init__(self, bot: Any, cfg: DropCfg, ctx: Any, logger: Any | None = None, debug: bool = True):
        self.bot = bot
        self.cfg = cfg
        self.ctx = ctx
        self.log = logger
        self.debug = debug

    async def step(self) -> None:
        if not self.cfg.enabled:
            return
        # TODO: implementar drop real depois
        return
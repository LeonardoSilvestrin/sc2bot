from __future__ import annotations

from dataclasses import dataclass

from bot.strategy.schema import DropCfg


class DropBehavior:
    def __init__(self, bot, cfg: DropCfg, state, debug: bool = True):
        self.bot = bot
        self.cfg = cfg
        self.state = state
        self.debug = debug

    async def step(self):
        # TODO: implementar drop real depois
        return

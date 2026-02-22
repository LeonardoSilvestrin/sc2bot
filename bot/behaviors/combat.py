# behaviors/combat.py
from __future__ import annotations

from typing import Any


class CombatBehavior:
    def __init__(self, bot: Any, ctx: Any, logger: Any | None = None, debug: bool = True):
        self.bot = bot
        self.ctx = ctx
        self.log = logger
        self.debug = debug

    async def step(self) -> None:
        return
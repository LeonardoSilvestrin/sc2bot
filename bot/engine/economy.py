# economy.py
from __future__ import annotations

from typing import Any

from sc2.ids.unit_typeid import UnitTypeId as U


class Economy:
    def __init__(self, bot: Any, *, ctx: Any | None = None, logger: Any | None = None):
        self.bot = bot
        self.ctx = ctx
        self.log = logger

    async def step(self) -> None:
        # python-sc2 worker distribution
        await self.bot.distribute_workers()

    async def train_scv(self, target: int) -> bool:
        """Treina SCV até atingir target (conta pending)."""
        bot = self.bot
        if not bot.townhalls.ready:
            return False

        scv_total = bot.workers.amount + bot.already_pending(U.SCV)
        if scv_total >= int(target):
            return False

        cc = bot.townhalls.ready.first
        if cc.is_idle and bot.can_afford(U.SCV) and bot.supply_left > 0:
            cc.train(U.SCV)
            if self.log:
                self.log.emit(
                    "econ_train_scv",
                    {"target": int(target), "scv_total": int(scv_total) + 1},
                    meta={"iter": int(getattr(self.ctx, "iteration", 0))},
                )
            return True

        return False
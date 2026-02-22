# economy.py
from __future__ import annotations

from typing import Any, Optional

from sc2.ids.unit_typeid import UnitTypeId as U


class Economy:
    """
    Homeostase econômica:
    - distribui workers
    - treina SCV até target
    Não decide estratégia (isso é executor/behaviors).
    """

    def __init__(self, bot: Any, ctx: Any | None = None, logger: Any | None = None):
        self.bot = bot
        self.ctx = ctx
        self.log = logger

    async def step(self) -> None:
        # python-sc2: distribuição automática
        await self.bot.distribute_workers()

    async def train_scv(self, target: int) -> bool:
        """Treina SCV até atingir target (conta pending)."""
        bot = self.bot

        # compatível com forks diferentes: townhalls pode existir, ou não
        townhalls = getattr(bot, "townhalls", None)
        if not townhalls or not townhalls.ready:
            return False

        scv_count = int(bot.workers.amount) + int(bot.already_pending(U.SCV))
        if scv_count >= int(target):
            return False

        cc = townhalls.ready.first
        if not cc.is_idle:
            return False
        if bot.supply_left <= 0:
            return False
        if not bot.can_afford(U.SCV):
            return False

        cc.train(U.SCV)

        if self.log and self.ctx:
            self.log.emit(
                "econ_train_scv",
                {"target": int(target), "scv_total": int(scv_count) + 1},
                meta={"iter": int(self.ctx.iteration)},
            )

        return True
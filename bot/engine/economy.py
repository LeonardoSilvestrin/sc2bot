from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId as U


class Economy:
    def __init__(self, bot):
        self.bot = bot

    async def step(self):
        # worker distribution do python-sc2
        await self.bot.distribute_workers()

    async def train_scv(self, target: int) -> bool:
        """Treina SCV até atingir target (conta pending)."""
        bot = self.bot
        if not bot.townhalls.ready:
            return False

        scv_count = bot.workers.amount + bot.already_pending(U.SCV)
        if scv_count >= target:
            return False

        cc = bot.townhalls.ready.first
        if cc.is_idle and bot.can_afford(U.SCV) and bot.supply_left > 0:
            cc.train(U.SCV)
            return True

        return False
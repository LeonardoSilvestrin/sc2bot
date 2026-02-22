from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId as U


class Builder:
    def __init__(self, bot, economy, placement, state):
        self.bot = bot
        self.economy = economy
        self.placement = placement
        self.state = state

    # ----------------------------
    # counts (engine helpers)
    # ----------------------------
    def have(self, unit_type: U) -> int:
        return self.bot.units(unit_type).amount

    def ready(self, unit_type: U) -> int:
        return self.bot.units(unit_type).ready.amount

    def pending(self, unit_type: U) -> int:
        return self.bot.already_pending(unit_type)

    def total(self, unit_type: U) -> int:
        # conta existente + em construção/treinamento
        return self.have(unit_type) + self.pending(unit_type)

    # ----------------------------
    # actions (idempotent-ish)
    # ----------------------------
    async def try_build(self, unit_type: U, *, near=None) -> bool:
        bot = self.bot

        if not bot.can_afford(unit_type):
            return False

        # Não tenta construir se não tem worker
        if bot.workers.amount == 0:
            return False

        pos = await self.placement.find_placement(unit_type, near=near)
        if pos is None:
            return False

        await bot.build(unit_type, near=pos)
        return True

    async def try_train(self, unit_type: U, *, from_type: U) -> bool:
        bot = self.bot
        buildings = bot.units(from_type).ready
        if not buildings:
            return False

        if not bot.can_afford(unit_type):
            return False

        if bot.supply_left <= 0:
            return False

        for b in buildings:
            # key: só treina se idle (sem orders)
            if not b.is_idle:
                continue

            # emite o comando
            b.train(unit_type)
            return True

        return False
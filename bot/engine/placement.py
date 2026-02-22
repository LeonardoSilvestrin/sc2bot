from __future__ import annotations

from sc2.position import Point2


class Placement:
    def __init__(self, bot):
        self.bot = bot

    async def find_placement(self, unit_type, *, near: Point2 | None = None) -> Point2 | None:
        bot = self.bot
        if near is None:
            if bot.townhalls.ready:
                near = bot.townhalls.ready.first.position
            else:
                near = bot.start_location

        # placement_step=2 é bom equilíbrio de custo/qualidade
        pos = await bot.find_placement(unit_type, near=near, placement_step=2)
        return pos
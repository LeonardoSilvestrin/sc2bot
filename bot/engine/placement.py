# placement.py
from __future__ import annotations

from typing import Any

from sc2.position import Point2


class Placement:
    def __init__(self, bot: Any, *, ctx: Any | None = None, logger: Any | None = None):
        self.bot = bot
        self.ctx = ctx
        self.log = logger

    async def find_placement(self, unit_type, *, near: Point2 | None = None) -> Point2 | None:
        bot = self.bot
        if near is None:
            if bot.townhalls.ready:
                near = bot.townhalls.ready.first.position
            else:
                near = bot.start_location

        pos = await bot.find_placement(unit_type, near=near, placement_step=2)
        return pos
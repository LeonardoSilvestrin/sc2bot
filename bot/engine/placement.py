# placement.py
from __future__ import annotations

from typing import Any, Optional

from sc2.position import Point2


class Placement:
    """
    Encapsula find_placement do python-sc2.
    - Se near não for passado, usa CC ou start_location.
    """

    def __init__(self, bot: Any, ctx: Any | None = None, logger: Any | None = None):
        self.bot = bot
        self.ctx = ctx
        self.log = logger

    async def find_placement(self, unit_type, *, near: Point2 | None = None) -> Point2 | None:
        bot = self.bot

        if near is None:
            townhalls = getattr(bot, "townhalls", None)
            if townhalls and townhalls.ready:
                near = townhalls.ready.first.position
            else:
                near = bot.start_location

        try:
            pos = await bot.find_placement(unit_type, near=near, placement_step=2)
        except Exception as e:
            if self.log and self.ctx:
                self.log.emit(
                    "placement_error",
                    {"unit": getattr(unit_type, "name", str(unit_type)), "err": str(e)},
                    meta={"iter": int(self.ctx.iteration)},
                )
            return None

        if pos is None and self.log and self.ctx:
            self.log.emit(
                "placement_none",
                {"unit": getattr(unit_type, "name", str(unit_type))},
                meta={"iter": int(self.ctx.iteration)},
            )

        return pos
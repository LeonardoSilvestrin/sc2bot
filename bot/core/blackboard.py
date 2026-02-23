#bot/core/blackboard.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sc2.position import Point2


@dataclass
class Blackboard:
    opening_done: bool = False
    enemy_main: Optional[Point2] = None
    threatened: bool = False

    @staticmethod
    def build(bot) -> "Blackboard":
        bb = Blackboard()
        try:
            bb.opening_done = bool(getattr(bot.build_order_runner, "build_completed", False))
        except Exception:
            bb.opening_done = False

        # enemy main best-effort
        try:
            if bot.enemy_start_locations:
                bb.enemy_main = bot.enemy_start_locations[0]
        except Exception:
            bb.enemy_main = None

        return bb
# bot/ares_wrapper/map.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple

from sc2.position import Point2


EnemyMainSource = Literal["ENEMY_START"]


@dataclass(frozen=True)
class Map:
    bot: object

    def enemy_main(self) -> Tuple[Point2, EnemyMainSource]:
        """
        Strict contract: no fallbacks.
        If the engine cannot provide enemy_start_locations, crash to expose wiring issues.
        """
        locs = getattr(self.bot, "enemy_start_locations", None)
        if not locs or len(locs) == 0:
            raise RuntimeError("Map.enemy_main() requires bot.enemy_start_locations[0]")
        return locs[0], "ENEMY_START"
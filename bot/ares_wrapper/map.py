#bot/ares_wrapper/map.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple

from sc2.position import Point2


EnemyMainSource = Literal["ENEMY_START", "FALLBACK_CENTER", "FALLBACK_START"]


@dataclass(frozen=True)
class Map:
    bot: object

    def enemy_main(self) -> Tuple[Point2, EnemyMainSource]:
        # 1) normal
        try:
            locs = getattr(self.bot, "enemy_start_locations", None)
            if locs and len(locs) > 0:
                return locs[0], "ENEMY_START"
        except Exception:
            pass

        # 2) fallback map center
        try:
            return self.bot.game_info.map_center, "FALLBACK_CENTER"
        except Exception:
            pass

        # 3) fallback final
        return self.bot.start_location, "FALLBACK_START"
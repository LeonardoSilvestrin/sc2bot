#bot/services/map.py
from __future__ import annotations

from dataclasses import dataclass

from sc2.position import Point2


@dataclass(frozen=True)
class MapService:
    """
    Encapsula leituras de "onde ir" no mapa.

    Sem fallback:
    - Se enemy_start_locations não existir ou estiver vazio -> crash.
    """

    bot: object  # AresBot / BotAI

    def enemy_main(self) -> Point2:
        return self.bot.enemy_start_locations[0]
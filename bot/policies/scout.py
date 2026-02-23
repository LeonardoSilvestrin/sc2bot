#bot/policies/scout.py
from __future__ import annotations

from dataclasses import dataclass

from sc2.unit import Unit

from bot.services.map import MapService
from bot.services.roles import RoleService


@dataclass
class ScoutState:
    dispatched: bool = False
    scout_tag: int | None = None


class ScoutPolicy:
    """
    MVP de scout:
      - quando chamado, se ainda não despachou:
          - pega 1 SCV via RoleService.request_worker_scout()
          - manda mover/atacar-move até a main inimiga (aqui: move simples)
          - marca dispatched

    Sem fallback.
    """

    def __init__(self) -> None:
        self.state = ScoutState()

    async def act(self, bot, *, roles: RoleService, maps: MapService) -> bool:
        if self.state.dispatched:
            return False

        target = maps.enemy_main()

        scout: Unit = roles.request_worker_scout(target_position=target)
        scout.move(target)

        self.state.dispatched = True
        self.state.scout_tag = scout.tag
        return True
#bot/policies/threat.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2
from sc2.unit import Unit


@dataclass
class ThreatReport:
    threatened: bool
    threat_pos: Optional[Point2]
    enemy_count: int
    radius: float


class ThreatPolicy:
    """
    Defesa reativa simples:
      - Detecta inimigos perto de qualquer townhall (CC/OC/PF).
      - Se ameaçado, comanda exército básico para defender.

    Observação: isso NÃO é "boa defesa", é "não morrer de graça".
    """

    def __init__(self, *, defend_radius: float = 22.0, min_enemy: int = 1):
        self.defend_radius = defend_radius
        self.min_enemy = min_enemy

    def _townhalls(self, bot) -> List[Unit]:
        # AresBot herda BotAI => townhalls existe no python-sc2
        try:
            return list(bot.townhalls)
        except Exception:
            return []

    def evaluate(self, bot) -> ThreatReport:
        ths = self._townhalls(bot)
        if not ths:
            return ThreatReport(False, None, 0, self.defend_radius)

        enemies = bot.enemy_units
        if not enemies:
            return ThreatReport(False, None, 0, self.defend_radius)

        best: Tuple[int, Optional[Point2]] = (0, None)
        for th in ths:
            near = enemies.closer_than(self.defend_radius, th.position)
            c = near.amount
            if c > best[0]:
                best = (c, th.position)

        threatened = best[0] >= self.min_enemy
        return ThreatReport(threatened, best[1], best[0], self.defend_radius)

    async def act(self, bot, report: ThreatReport) -> bool:
        """
        Retorna True se emitiu comandos relevantes.
        """
        if not report.threatened or not report.threat_pos:
            return False

        # Grupo de defesa: começa simples (bio)
        defenders = bot.units.of_type(
            {
                U.MARINE,
                U.MARAUDER,
                U.SIEGETANK,
                U.SIEGETANKSIEGED,
                U.HELLION,
                U.HELLBAT,
                U.CYCLONE,
                U.THOR,
                U.THORAP,
                U.MEDIVAC,
            }
        )

        if defenders.amount == 0:
            return False

        # Não puxa tudo do mapa inteiro; só quem está relativamente perto
        local = defenders.closer_than(45, report.threat_pos)
        if local.amount == 0:
            # fallback: puxa tudo
            local = defenders

        # Medivac não precisa suicidar: manda seguir/ir para trás levemente
        medivacs = local(U.MEDIVAC)
        army = local - medivacs

        issued = False
        for u in army:
            if u.is_idle:
                u.attack(report.threat_pos)
                issued = True

        for m in medivacs:
            if m.is_idle:
                m.move(report.threat_pos.towards(bot.start_location, 6))
                issued = True

        return issued
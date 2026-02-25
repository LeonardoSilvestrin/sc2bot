# bot/tasks/defend.py
from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.tasks.base_task import BaseTask, TaskTick


@dataclass
class Defend(BaseTask):
    """
    Defesa reativa das bases.

    Contrato:
      - Implementa Task via BaseTask (status(), pause(), abort(), etc).
      - Consome budget quando emite comandos.
    """

    log: DevLogger | None = None
    log_every_iters: int = 11

    def __init__(self, *, log: DevLogger | None = None, log_every_iters: int = 11):
        super().__init__(task_id="defend_bases", domain="DEFENSE", commitment=90)
        self.log = log
        self.log_every_iters = int(log_every_iters)

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> bool:
        if not attention.combat.threatened or not attention.combat.threat_pos:
            self._paused("no_threat")
            return False

        defenders = bot.units.of_type(
            {
                U.MARINE,
                U.MARAUDER,
                U.SIEGETANK,
                U.SIEGETANKSIEGED,
                U.HELLION,
                U.CYCLONE,
                U.THOR,
                U.THORAP,
                U.MEDIVAC,
            }
        )
        if defenders.amount == 0:
            self._paused("no_defenders")
            return False

        local = defenders.closer_than(45, attention.combat.threat_pos)
        if local.amount == 0:
            local = defenders

        medivacs = local(U.MEDIVAC)
        army = local - medivacs

        issued = False

        for u in army:
            if u.is_idle:
                u.attack(attention.combat.threat_pos)
                issued = True

        for m in medivacs:
            if m.is_idle:
                m.move(attention.combat.threat_pos.towards(bot.start_location, 6))
                issued = True

        if issued:
            self._active("defending")
            if self.log and (tick.iteration % self.log_every_iters == 0):
                self.log.emit(
                    "defend_tick",
                    {
                        "iteration": int(tick.iteration),
                        "time": round(float(getattr(bot, "time", 0.0)), 2),
                        "enemy_count": int(attention.combat.enemy_count_near_bases),
                        "urgency": int(attention.combat.defense_urgency),
                        "pos": [round(attention.combat.threat_pos.x, 1), round(attention.combat.threat_pos.y, 1)],
                    },
                )
        else:
            self._active("defending_no_orders")

        return bool(issued)
from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.mind.attention import Attention
from bot.tasks.base import TaskStatus, TaskTick


class Defend:
    task_id = "defend_bases"
    domain = "DEFENSE"
    commitment = 90
    status = TaskStatus.ACTIVE

    def is_done(self) -> bool:
        return False

    def evaluate(self, bot, attention: Attention) -> int:
        if not attention.threatened or not attention.threat_pos:
            return 0
        return 50 + int(attention.defense_urgency)

    async def pause(self, bot, reason: str) -> None:
        bot.log.emit("defend_pause_ignored", {"reason": reason})

    async def abort(self, bot, reason: str) -> None:
        bot.log.emit("defend_abort_ignored", {"reason": reason})

    async def step(self, bot, tick: TaskTick, attention: Attention) -> bool:
        if not attention.threatened or not attention.threat_pos:
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
            return False

        local = defenders.closer_than(45, attention.threat_pos)
        if local.amount == 0:
            local = defenders

        medivacs = local(U.MEDIVAC)
        army = local - medivacs

        issued = False
        for u in army:
            if u.is_idle:
                u.attack(attention.threat_pos)
                issued = True

        for m in medivacs:
            if m.is_idle:
                m.move(attention.threat_pos.towards(bot.start_location, 6))
                issued = True

        if issued and tick.iteration % 11 == 0:
            bot.log.emit(
                "defend_tick",
                {
                    "iteration": tick.iteration,
                    "time": round(bot.time, 2),
                    "enemy_count": int(attention.enemy_count_near_bases),
                    "urgency": int(attention.defense_urgency),
                    "pos": [round(attention.threat_pos.x, 1), round(attention.threat_pos.y, 1)],
                },
            )

        return issued
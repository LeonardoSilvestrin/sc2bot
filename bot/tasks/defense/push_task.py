from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.mind.attention import Attention
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick

_COMBAT_TYPES = {
    U.MARINE,
    U.MARAUDER,
    U.SIEGETANK,
    U.HELLION,
    U.CYCLONE,
    U.THOR,
    U.THORAP,
    U.MEDIVAC,
}


@dataclass
class PushTask(BaseTask):
    target_pos: Point2
    end_t: float

    def __init__(self, *, target_pos: Point2, end_t: float) -> None:
        super().__init__(task_id="timing_push", domain="DEFENSE", commitment=62)
        self.target_pos = target_pos
        self.end_t = float(end_t)

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        now = float(tick.time)

        if now > self.end_t:
            self._done("window_ended")
            return TaskResult.done("window_ended")

        if int(attention.combat.primary_urgency) >= 50:
            self._paused("defense_priority")
            return TaskResult.noop("defense_priority")

        try:
            units = bot.units.of_type(_COMBAT_TYPES)
        except Exception:
            return TaskResult.noop("no_units")

        issued = False
        for u in units:
            try:
                if u.is_idle:
                    u.attack(self.target_pos)
                    issued = True
            except Exception:
                continue

        if issued:
            self._active("pushing")
            return TaskResult.running("pushing")
        return TaskResult.noop("no_idle_units")

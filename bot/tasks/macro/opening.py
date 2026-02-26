# bot/tasks/macro/opening.py
from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.tasks.base_task import BaseTask, TaskTick, TaskResult


@dataclass
class MacroOpeningTick(BaseTask):
    """
    Opening macro minimalista:
      - SCV contínuo até scv_cap

    Mantido simples de propósito. (BuildRunner/YML pode cuidar do resto do opening.)
    """
    log: DevLogger | None = None
    log_every_iters: int = 22
    scv_cap: int = 60

    def __init__(self, *, log: DevLogger | None = None, log_every_iters: int = 22, scv_cap: int = 60):
        super().__init__(task_id="macro_opening_scv_only", domain="MACRO", commitment=10)
        self.log = log
        self.log_every_iters = int(log_every_iters)
        self.scv_cap = int(scv_cap)

    def _workers(self, bot) -> int:
        return int(bot.workers.amount)

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        ths = bot.townhalls.ready
        if ths.amount == 0:
            self._paused("no_townhalls")
            return TaskResult.noop("no_townhalls")

        if int(bot.supply_left) <= 0:
            self._paused("no_supply")
            return TaskResult.noop("no_supply")

        if self._workers(bot) >= self.scv_cap:
            self._active("scv_cap")
            return TaskResult.noop("scv_cap")

        if not bot.can_afford(U.SCV):
            self._paused("cant_afford_scv")
            return TaskResult.noop("cant_afford_scv")

        idle_ths = ths.idle
        if idle_ths.amount == 0:
            self._active("townhalls_busy")
            return TaskResult.noop("townhalls_busy")

        idle_ths.first.train(U.SCV)
        self._active("training_scv_opening")

        if self.log and (tick.iteration % self.log_every_iters == 0):
            self.log.emit(
                "macro_opening",
                {"iter": int(tick.iteration), "t": round(float(tick.time), 2), "action": "train_scv"},
            )

        return TaskResult.running("train_scv")
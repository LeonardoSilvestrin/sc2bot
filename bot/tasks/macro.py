# bot/tasks/macro.py
from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.tasks.base import BaseTask, TaskTick


@dataclass
class MacroBasic(BaseTask):
    """
    Macro MVP:
      - SCV contínuo (sem cap aqui; cap/limites ficam a cargo do Ares/YAML/config futuro).
      - Não depende de opening_done: se houver townhall idle + supply + afford -> train SCV.
      - Consome budget apenas quando emitir train().
    """

    log: DevLogger | None = None
    log_every_iters: int = 22

    def __init__(
        self,
        *,
        log: DevLogger | None = None,
        log_every_iters: int = 22,
    ):
        # commitment baixo: macro é baseline, não deve "bloquear" outros domínios.
        super().__init__(task_id="macro_basic", domain="MACRO", commitment=5)
        self.log = log
        self.log_every_iters = int(log_every_iters)

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> bool:
        # Se não temos townhalls, não há o que fazer.
        try:
            ths = bot.townhalls.ready
        except Exception:
            ths = None

        if not ths or ths.amount == 0:
            self._paused("no_townhalls")
            return False

        # Precisa de supply e recursos.
        if int(getattr(bot, "supply_left", 0) or 0) <= 0:
            self._paused("no_supply")
            return False

        if not bot.can_afford(U.SCV):
            self._paused("cant_afford_scv")
            return False

        idle_ths = ths.idle
        if idle_ths.amount == 0:
            self._active("townhalls_busy")
            return False

        th = idle_ths.first
        th.train(U.SCV)

        self._active("training_scv")

        if self.log and (int(tick.iteration) % self.log_every_iters == 0):
            try:
                worker_count = int(bot.workers.amount)
            except Exception:
                worker_count = 0

            self.log.emit(
                "macro_train_scv",
                {
                    "iteration": int(tick.iteration),
                    "time": round(float(tick.time), 2),
                    "workers": worker_count,
                },
            )

        return True
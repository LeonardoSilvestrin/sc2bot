# bot/tasks/macro_task.py
from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId as Up

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.tasks.base_task import BaseTask, TaskTick, TaskResult


@dataclass
class MacroOpeningTick(BaseTask):
    """
    Opening macro minimalista:
      - SCV contínuo até scv_cap
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
            self.log.emit("macro_opening", {"iter": int(tick.iteration), "t": round(float(tick.time), 2), "action": "train_scv"})

        return TaskResult.running("train_scv")


@dataclass
class MacroBio2BaseTick(BaseTask):
    """
    BIO_2BASE Macro v0.1 (pós-opening) — MVP:
      - SCV contínuo até scv_cap
      - Barracks até 3 em 2 bases
      - Stimpack (se possível)
      - Medivac até 2
    """
    log: DevLogger | None = None
    log_every_iters: int = 22

    scv_cap: int = 60
    target_bases: int = 3

    backoff_urgency: int = 60

    def __init__(
        self,
        *,
        log: DevLogger | None = None,
        log_every_iters: int = 22,
        scv_cap: int = 60,
        target_bases: int = 3,
        backoff_urgency: int = 60,
    ):
        super().__init__(task_id="macro_bio_2base_v01", domain="MACRO", commitment=15)
        self.log = log
        self.log_every_iters = int(log_every_iters)
        self.scv_cap = int(scv_cap)
        self.target_bases = int(target_bases)
        self.backoff_urgency = int(backoff_urgency)

    def _bases_ready(self, bot) -> int:
        return int(bot.townhalls.ready.amount)

    def _workers(self, bot) -> int:
        return int(bot.workers.amount)

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        if bool(attention.combat.threatened) and int(attention.combat.defense_urgency) >= int(self.backoff_urgency):
            self._paused("backoff_threat")
            return TaskResult.noop("backoff_threat")

        did_any = False

        ths = bot.townhalls.ready
        if ths.amount > 0 and int(bot.supply_left) > 0 and self._workers(bot) < self.scv_cap and bot.can_afford(U.SCV):
            idle = ths.idle
            if idle.amount > 0:
                idle.first.train(U.SCV)
                did_any = True
                self._active("train_scv")

        bases = self._bases_ready(bot)
        target_rax = 1 if bases <= 1 else 3
        rax_ready = int(bot.structures(U.BARRACKS).ready.amount)
        rax_pending = int(bot.already_pending(U.BARRACKS))

        if rax_ready + rax_pending < target_rax and bot.can_afford(U.BARRACKS):
            worker = bot.select_build_worker(bot.start_location)
            if worker is not None:
                pos = bot.start_location.towards(bot.game_info.map_center, 6)
                bot.build(U.BARRACKS, near=pos)
                did_any = True
                self._active("build_barracks")

        if Up.STIMPACK not in bot.state.upgrades:
            if bot.structures(U.BARRACKSTECHLAB).ready.amount > 0 and bot.can_afford(Up.STIMPACK):
                tl = bot.structures(U.BARRACKSTECHLAB).ready.first
                tl.research(Up.STIMPACK)
                did_any = True
                self._active("research_stim")

        medivacs = int(bot.units(U.MEDIVAC).amount)
        if medivacs < 2 and bot.structures(U.STARPORT).ready.amount > 0 and bot.can_afford(U.MEDIVAC):
            sp = bot.structures(U.STARPORT).ready.first
            if sp.is_idle:
                sp.train(U.MEDIVAC)
                did_any = True
                self._active("train_medivac")

        if self.log and (tick.iteration % self.log_every_iters == 0):
            self.log.emit("macro_tick", {"iter": int(tick.iteration), "t": round(float(tick.time), 2), "did_any": bool(did_any), "reason": self.last_reason()})

        return TaskResult.running(self.last_reason()) if did_any else TaskResult.noop(self.last_reason())
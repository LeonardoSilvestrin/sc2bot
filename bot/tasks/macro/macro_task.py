# bot/tasks/macro_task.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from ares.behaviors.macro.auto_supply import AutoSupply
from ares.behaviors.macro.build_workers import BuildWorkers
from ares.behaviors.macro.expansion_controller import ExpansionController
from ares.behaviors.macro.gas_building_controller import GasBuildingController
from ares.behaviors.macro.macro_plan import MacroPlan
from ares.behaviors.macro.production_controller import ProductionController
from ares.behaviors.macro.spawn_controller import SpawnController
from sc2.ids.unit_typeid import UnitTypeId as U

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.tasks.base_task import BaseTask, TaskTick, TaskResult


@dataclass
class MacroOpeningTick(BaseTask):
    """
    Opening macro minimalista:
      - SCV contínuo até scv_cap

    (Mantido propositalmente simples. O build runner/YML pode cuidar do resto do opening.)
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


# ---------------------------
# Ares-powered macro builds
# ---------------------------

def _register_macro_plan(bot, plan, *, log: DevLogger | None, tick: TaskTick, label: str) -> None:
    """
    Strict: relies on AresBot.register_behavior existing.
    This is inside macro task, not planner/ego.
    """
    bot.register_behavior(plan)
    if log and (tick.iteration % 22 == 0):
        log.emit("macro_ares_plan", {"iter": int(tick.iteration), "t": round(float(tick.time), 2), "label": str(label)})


@dataclass
class MacroAresBioStandardTick(BaseTask):
    """
    Standard macro (BIO-ish) using Ares MacroPlan behaviors.

    Goal: "never stalls" macro:
      - autosupply
      - continuous workers (to scv_cap)
      - expand to 2 bases (can bump later)
      - basic production + spawn loop (marines + occasional medivac)
    """
    log: DevLogger | None = None
    scv_cap: int = 66
    target_bases: int = 2

    def __init__(self, *, log: DevLogger | None = None, scv_cap: int = 66, target_bases: int = 2):
        super().__init__(task_id="macro_ares_bio_standard", domain="MACRO", commitment=15)
        self.log = log
        self.scv_cap = int(scv_cap)
        self.target_bases = int(target_bases)

    def _army_comp(self) -> Dict[U, int]:
        # Weights (not absolute caps). Keep simple & robust.
        return {
            U.MARINE: 10,
            U.MEDIVAC: 2,
        }

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        plan = MacroPlan()

        # Priority order matters: MacroPlan executes behaviors sequentially and stops after a successful one.
        plan.add(AutoSupply(base_location=bot.start_location))
        plan.add(BuildWorkers(to_count=int(self.scv_cap)))
        plan.add(GasBuildingController(to_count=max(0, int(len(bot.townhalls)) * 2)))
        plan.add(ExpansionController(to_base_count=int(self.target_bases)))
        plan.add(ProductionController())
        plan.add(SpawnController(army_composition_dict=self._army_comp()))

        _register_macro_plan(bot, plan, log=self.log, tick=tick, label="BIO_STANDARD")
        self._active("ares_macro_standard")
        return TaskResult.running("ares_macro_standard")


@dataclass
class MacroAresRushDefenseTick(BaseTask):
    """
    Rush-defense macro using Ares MacroPlan behaviors.

    Philosophy:
      - DO NOT expand
      - Keep workers going (but lower cap)
      - Spend on immediate army
      - Keep supply safe
    """
    log: DevLogger | None = None
    scv_cap: int = 40
    target_bases: int = 1

    def __init__(self, *, log: DevLogger | None = None, scv_cap: int = 40, target_bases: int = 1):
        super().__init__(task_id="macro_ares_rush_defense", domain="MACRO", commitment=20)
        self.log = log
        self.scv_cap = int(scv_cap)
        self.target_bases = int(target_bases)

    def _army_comp(self) -> Dict[U, int]:
        # Pure "don't die" comp. You can enrich later (marauder, bunker logic, etc).
        return {
            U.MARINE: 14,
        }

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        plan = MacroPlan()
        plan.add(AutoSupply(base_location=bot.start_location))
        plan.add(BuildWorkers(to_count=int(self.scv_cap)))
        plan.add(ExpansionController(to_base_count=int(self.target_bases)))  # locks at 1
        plan.add(ProductionController())
        plan.add(SpawnController(army_composition_dict=self._army_comp()))

        _register_macro_plan(bot, plan, log=self.log, tick=tick, label="RUSH_DEFENSE")
        self._active("ares_macro_rush_defense")
        return TaskResult.running("ares_macro_rush_defense")

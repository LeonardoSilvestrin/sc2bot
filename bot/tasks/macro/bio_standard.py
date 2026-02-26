# bot/tasks/macro/bio_standard.py
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
from bot.tasks.macro.ares_plan import register_macro_plan


@dataclass
class MacroAresBioStandardTick(BaseTask):
    """
    Standard macro (BIO-ish) using Ares MacroPlan behaviors.

    Goal: "never stalls" macro:
      - autosupply
      - continuous workers (to scv_cap)
      - expand to target_bases
      - basic production + spawn loop
    """
    log: DevLogger | None = None
    scv_cap: int = 66
    target_bases: int = 2
    log_every_iters: int = 22

    def __init__(self, *, log: DevLogger | None = None, scv_cap: int = 66, target_bases: int = 2, log_every_iters: int = 22):
        super().__init__(task_id="macro_ares_bio_standard", domain="MACRO", commitment=15)
        self.log = log
        self.scv_cap = int(scv_cap)
        self.target_bases = int(target_bases)
        self.log_every_iters = int(log_every_iters)

    def _army_comp(self) -> Dict[U, int]:
        # Weights (not caps). Keep simple & robust.
        return {
            U.MARINE: 10,
            U.MEDIVAC: 2,
        }

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        plan = MacroPlan()
        plan.add(AutoSupply(base_location=bot.start_location))
        plan.add(BuildWorkers(to_count=int(self.scv_cap)))
        plan.add(GasBuildingController(to_count=max(0, int(len(bot.townhalls)) * 2)))
        plan.add(ExpansionController(to_base_count=int(self.target_bases)))
        plan.add(ProductionController())
        plan.add(SpawnController(army_composition_dict=self._army_comp()))

        register_macro_plan(bot, plan, log=self.log, tick=tick, label="BIO_STANDARD", log_every_iters=self.log_every_iters)
        self._active("ares_macro_standard")
        return TaskResult.running("ares_macro_standard")

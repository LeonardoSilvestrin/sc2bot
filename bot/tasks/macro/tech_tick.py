from __future__ import annotations

from dataclasses import dataclass

from ares.behaviors.macro.macro_plan import MacroPlan
from ares.behaviors.macro.upgrade_controller import UpgradeController
from sc2.ids.upgrade_id import UpgradeId as Up

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class MacroTechTick(BaseTask):
    awareness: Awareness
    log: DevLogger | None = None
    log_every_iters: int = 22

    def __init__(self, *, awareness: Awareness, log: DevLogger | None = None, log_every_iters: int = 22):
        super().__init__(task_id="macro_tech", domain="MACRO_TECH", commitment=9)
        self.awareness = awareness
        self.log = log
        self.log_every_iters = int(log_every_iters)

    def _planned_upgrades(self, now: float) -> list:
        names = list(self.awareness.mem.get(K("macro", "tech", "plan", "upgrades"), now=now, default=[]) or [])
        upgrades: list = []
        for name in names:
            up = getattr(Up, str(name), None)
            if up is not None:
                upgrades.append(up)
        return upgrades

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound()
        if bound_err is not None:
            return bound_err

        now = float(tick.time)
        upgrades = self._planned_upgrades(now)
        if not upgrades:
            return TaskResult.noop("no_tech_plan")

        plan = MacroPlan()
        plan.add(
            UpgradeController(
                upgrade_list=upgrades,
                base_location=bot.start_location,
                auto_tech_up_enabled=True,
                prioritize=False,
            )
        )
        bot.register_behavior(plan)

        if self.log is not None and (int(tick.iteration) % self.log_every_iters == 0):
            reserve_m = int(self.awareness.mem.get(K("macro", "tech", "plan", "reserve_minerals"), now=now, default=0) or 0)
            reserve_g = int(self.awareness.mem.get(K("macro", "tech", "plan", "reserve_gas"), now=now, default=0) or 0)
            reserve_name = str(self.awareness.mem.get(K("macro", "tech", "plan", "reserve_name"), now=now, default="") or "")
            self.log.emit(
                "macro_tech",
                {
                    "iter": int(tick.iteration),
                    "t": round(float(now), 2),
                    "upgrades_head": [str(u.name) for u in upgrades[:6]],
                    "upgrade_count": int(len(upgrades)),
                    "tech_reserve_minerals": int(reserve_m),
                    "tech_reserve_gas": int(reserve_g),
                    "tech_reserve_name": str(reserve_name),
                },
            )

        return TaskResult.running("tech_plan_registered")


from __future__ import annotations

from dataclasses import dataclass

from ares.behaviors.macro.macro_plan import MacroPlan
from ares.behaviors.macro.upgrade_controller import UpgradeController
from sc2.ids.upgrade_id import UpgradeId as Up

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick
from bot.tasks.macro.utils.desired_comp import desired_comp_names


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

    def _desired_comp(self, now: float) -> dict[str, float]:
        return desired_comp_names(awareness=self.awareness, now=now)

    @staticmethod
    def _u(name: str):
        try:
            return getattr(Up, name)
        except Exception:
            return None

    def _upgrade_list(self, now: float) -> list:
        comp = self._desired_comp(now)
        infantry = float(comp.get("MARINE", 0.0)) + float(comp.get("MARAUDER", 0.0)) + float(comp.get("GHOST", 0.0))
        mech = float(comp.get("HELLION", 0.0)) + float(comp.get("SIEGETANK", 0.0)) + float(comp.get("CYCLONE", 0.0)) + float(comp.get("THOR", 0.0))
        air = float(comp.get("MEDIVAC", 0.0)) + float(comp.get("VIKINGFIGHTER", 0.0)) + float(comp.get("LIBERATOR", 0.0)) + float(comp.get("BANSHEE", 0.0)) + float(comp.get("RAVEN", 0.0))

        names: list[str] = []
        if infantry >= 0.35:
            names.extend(
                [
                    "STIMPACK",
                    "SHIELDWALL",
                    "PUNISHERGRENADES",
                    "TERRANINFANTRYWEAPONSLEVEL1",
                    "TERRANINFANTRYARMORSLEVEL1",
                    "TERRANINFANTRYWEAPONSLEVEL2",
                    "TERRANINFANTRYARMORSLEVEL2",
                    "TERRANINFANTRYWEAPONSLEVEL3",
                    "TERRANINFANTRYARMORSLEVEL3",
                ]
            )

        if mech >= 0.30:
            names.extend(
                [
                    "TERRANVEHICLEWEAPONSLEVEL1",
                    "TERRANVEHICLEANDSHIPARMORSLEVEL1",
                    "TERRANVEHICLEWEAPONSLEVEL2",
                    "TERRANVEHICLEANDSHIPARMORSLEVEL2",
                    "TERRANVEHICLEWEAPONSLEVEL3",
                    "TERRANVEHICLEANDSHIPARMORSLEVEL3",
                ]
            )

        if air >= 0.25:
            names.extend(
                [
                    "TERRANSHIPWEAPONSLEVEL1",
                    "TERRANVEHICLEANDSHIPARMORSLEVEL1",
                    "TERRANSHIPWEAPONSLEVEL2",
                    "TERRANVEHICLEANDSHIPARMORSLEVEL2",
                    "TERRANSHIPWEAPONSLEVEL3",
                    "TERRANVEHICLEANDSHIPARMORSLEVEL3",
                ]
            )

        if not names:
            names.extend(
                [
                    "STIMPACK",
                    "SHIELDWALL",
                    "TERRANINFANTRYWEAPONSLEVEL1",
                    "TERRANINFANTRYARMORSLEVEL1",
                ]
            )

        seen: set = set()
        upgrades: list = []
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            up = self._u(name)
            if up is not None:
                upgrades.append(up)
        return upgrades

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound()
        if bound_err is not None:
            return bound_err

        now = float(tick.time)
        upgrades = self._upgrade_list(now)
        if not upgrades:
            return TaskResult.noop("no_upgrades_selected")

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
            self.log.emit(
                "macro_tech",
                {
                    "iter": int(tick.iteration),
                    "t": round(float(now), 2),
                    "upgrades_head": [str(u.name) for u in upgrades[:6]],
                    "upgrade_count": int(len(upgrades)),
                },
            )

        return TaskResult.running("tech_plan_registered")


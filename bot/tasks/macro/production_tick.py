from __future__ import annotations

from dataclasses import dataclass

from ares.behaviors.macro.build_workers import BuildWorkers
from ares.behaviors.macro.macro_plan import MacroPlan
from ares.behaviors.macro.spawn_controller import SpawnController
from sc2.ids.unit_typeid import UnitTypeId as U

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskTick, TaskResult
from bot.tasks.macro.utils.desired_comp import desired_comp_units, desired_priority_units, unit_comp_to_controller_dict


@dataclass
class MacroProductionTick(BaseTask):
    awareness: Awareness
    log: DevLogger | None = None
    scv_cap: int = 66
    log_every_iters: int = 22

    def __init__(
        self,
        *,
        awareness: Awareness,
        log: DevLogger | None = None,
        scv_cap: int = 66,
        log_every_iters: int = 22,
    ):
        super().__init__(task_id="macro_production", domain="MACRO_PRODUCTION", commitment=10)
        self.awareness = awareness
        self.log = log
        self.scv_cap = int(scv_cap)
        self.log_every_iters = int(log_every_iters)

    def _spawn_dict(self, now: float) -> dict[U, dict[str, float | int]]:
        comp = desired_comp_units(awareness=self.awareness, now=now)
        priority = desired_priority_units(awareness=self.awareness, now=now)
        return unit_comp_to_controller_dict(comp, priority_units=priority)

    def _morph_reserve(self, *, now: float) -> tuple[int, int]:
        reserve_m = int(self.awareness.mem.get(K("macro", "morph", "reserve_minerals"), now=now, default=0) or 0)
        reserve_g = int(self.awareness.mem.get(K("macro", "morph", "reserve_gas"), now=now, default=0) or 0)
        return reserve_m, reserve_g

    def _priority_reserve(self, *, now: float) -> tuple[int, int, str]:
        reserve_m = int(self.awareness.mem.get(K("macro", "desired", "reserve_minerals"), now=now, default=0) or 0)
        reserve_g = int(self.awareness.mem.get(K("macro", "desired", "reserve_gas"), now=now, default=0) or 0)
        reserve_unit = str(self.awareness.mem.get(K("macro", "desired", "reserve_unit"), now=now, default="") or "")
        return reserve_m, reserve_g, reserve_unit

    def _rush_state(self, *, now: float) -> str:
        return str(self.awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()

    def _parity_signal(self, *, now: float) -> tuple[str, str, str, int, int]:
        overall = str(self.awareness.mem.get(K("strategy", "parity", "overall"), now=now, default="EVEN") or "EVEN")
        econ = str(self.awareness.mem.get(K("strategy", "parity", "econ"), now=now, default="EVEN") or "EVEN")
        army = str(self.awareness.mem.get(K("strategy", "parity", "army"), now=now, default="EVEN") or "EVEN")
        expand_bias = int(self.awareness.mem.get(K("strategy", "parity", "expand_bias"), now=now, default=0) or 0)
        army_bias = int(self.awareness.mem.get(K("strategy", "parity", "army_bias"), now=now, default=0) or 0)
        return overall, econ, army, expand_bias, army_bias

    @staticmethod
    def _is_rush_active(state: str) -> bool:
        return str(state).upper() in {"SUSPECTED", "CONFIRMED", "HOLDING"}

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound()
        if bound_err is not None:
            return bound_err

        now = float(tick.time)
        rush_state = self._rush_state(now=now)
        rush_active = self._is_rush_active(rush_state)
        parity_overall, parity_econ, parity_army, expand_bias, army_bias = self._parity_signal(now=now)
        morph_m, morph_g = self._morph_reserve(now=now)
        prio_m, prio_g, prio_unit = self._priority_reserve(now=now)
        reserve_m = max(int(morph_m), int(prio_m))
        reserve_g = max(int(morph_g), int(prio_g))
        if int(attention.economy.minerals) < int(reserve_m) or int(attention.economy.gas) < int(reserve_g):
            if self.log is not None and (int(tick.iteration) % self.log_every_iters == 0):
                self.log.emit(
                    "macro_production",
                    {
                        "iter": int(tick.iteration),
                        "t": round(float(now), 2),
                        "action": "morph_reserve_hold",
                        "reserve_minerals": int(reserve_m),
                        "reserve_gas": int(reserve_g),
                        "minerals": int(attention.economy.minerals),
                        "gas": int(attention.economy.gas),
                        "reserve_unit": str(prio_unit),
                    },
                )
            return TaskResult.running("production_reserved_for_morph")

        spawn_dict = self._spawn_dict(now)
        orbitals_total = int(bot.structures(U.ORBITALCOMMAND).ready.amount + bot.already_pending(U.ORBITALCOMMAND))
        townhalls_total = int(bot.townhalls.ready.amount)
        required_orbitals_now = min(3, townhalls_total)
        allow_worker_production = orbitals_total >= required_orbitals_now
        if rush_active and int(attention.economy.workers_total) >= 30 and int(attention.economy.minerals) <= 450:
            allow_worker_production = False
        if int(army_bias) > 0 and int(attention.economy.workers_total) >= 28 and int(attention.economy.minerals) <= 700:
            allow_worker_production = False

        dynamic_scv_cap = int(self.scv_cap)
        if int(expand_bias) > 0:
            dynamic_scv_cap = min(85, dynamic_scv_cap + 6)
        elif int(army_bias) > 0:
            dynamic_scv_cap = max(30, dynamic_scv_cap - 8)

        freeflow_threshold = 1200
        if int(army_bias) > 0:
            freeflow_threshold = 900

        plan = MacroPlan()
        if allow_worker_production:
            plan.add(BuildWorkers(to_count=int(dynamic_scv_cap)))
        plan.add(
            SpawnController(
                army_composition_dict=spawn_dict,
                freeflow_mode=bool(attention.economy.minerals >= int(freeflow_threshold)),
                ignore_proportions_below_unit_count=8,
                over_produce_on_low_tech=True,
            )
        )

        bot.register_behavior(plan)

        if self.log is not None and (int(tick.iteration) % self.log_every_iters == 0):
            self.log.emit(
                "macro_production",
                {
                    "iter": int(tick.iteration),
                    "t": round(float(now), 2),
                    "scv_cap": int(self.scv_cap),
                    "dynamic_scv_cap": int(dynamic_scv_cap),
                    "workers_enabled": bool(allow_worker_production),
                    "orbitals_total": int(orbitals_total),
                    "required_orbitals_now": int(required_orbitals_now),
                    "townhalls_total": int(townhalls_total),
                    "units": [u.name for u in spawn_dict.keys()],
                    "freeflow_threshold": int(freeflow_threshold),
                    "reserve_minerals": int(reserve_m),
                    "reserve_gas": int(reserve_g),
                    "reserve_unit": str(prio_unit),
                    "rush_state": str(rush_state),
                    "rush_active": bool(rush_active),
                    "parity_overall": str(parity_overall),
                    "parity_econ": str(parity_econ),
                    "parity_army": str(parity_army),
                    "parity_expand_bias": int(expand_bias),
                    "parity_army_bias": int(army_bias),
                },
            )

        if not allow_worker_production:
            return TaskResult.running("production_plan_registered_orbital_priority")
        return TaskResult.running("production_plan_registered")


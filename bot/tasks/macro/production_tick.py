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


def _spawn_dict_from_names(raw: dict) -> dict[U, dict[str, float | int]]:
    out: dict[U, dict[str, float | int]] = {}
    if not isinstance(raw, dict):
        return out
    for name, cfg in raw.items():
        try:
            unit_type = getattr(U, str(name))
        except Exception:
            continue
        if not isinstance(cfg, dict):
            continue
        out[unit_type] = dict(cfg)
    return out


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

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound()
        if bound_err is not None:
            return bound_err

        now = float(tick.time)
        morph_reserve_m = int(self.awareness.mem.get(K("macro", "morph", "reserve_minerals"), now=now, default=0) or 0)
        morph_reserve_g = int(self.awareness.mem.get(K("macro", "morph", "reserve_gas"), now=now, default=0) or 0)
        tech_reserve_m = int(self.awareness.mem.get(K("macro", "reserve", "tech", "minerals"), now=now, default=0) or 0)
        tech_reserve_g = int(self.awareness.mem.get(K("macro", "reserve", "tech", "gas"), now=now, default=0) or 0)
        reserve_tech_name = str(self.awareness.mem.get(K("macro", "reserve", "tech", "name"), now=now, default="") or "")
        reserve_spending_name = str(self.awareness.mem.get(K("macro", "reserve", "spending", "name"), now=now, default="") or "")
        spending_reserve_m = int(self.awareness.mem.get(K("macro", "reserve", "spending", "minerals"), now=now, default=0) or 0)
        spending_reserve_g = int(self.awareness.mem.get(K("macro", "reserve", "spending", "gas"), now=now, default=0) or 0)
        reserve_m = max(int(morph_reserve_m), int(tech_reserve_m))
        reserve_g = max(int(morph_reserve_g), int(tech_reserve_g))
        hold_for_reserve = bool(int(attention.economy.minerals) < int(reserve_m) or int(attention.economy.gas) < int(reserve_g))
        workers_enabled = bool(self.awareness.mem.get(K("macro", "production", "plan", "workers_enabled"), now=now, default=True))
        dynamic_scv_cap = int(self.awareness.mem.get(K("macro", "production", "plan", "dynamic_scv_cap"), now=now, default=self.scv_cap) or self.scv_cap)
        freeflow_mode = bool(self.awareness.mem.get(K("macro", "production", "plan", "freeflow_mode"), now=now, default=False))
        rush_state = str(self.awareness.mem.get(K("macro", "production", "plan", "rush_state"), now=now, default="NONE") or "NONE")
        parity_overall = str(self.awareness.mem.get(K("macro", "production", "plan", "parity_overall"), now=now, default="EVEN") or "EVEN")
        parity_econ = str(self.awareness.mem.get(K("macro", "production", "plan", "parity_econ"), now=now, default="EVEN") or "EVEN")
        parity_army = str(self.awareness.mem.get(K("macro", "production", "plan", "parity_army"), now=now, default="EVEN") or "EVEN")
        spawn_dict_raw = self.awareness.mem.get(K("macro", "production", "plan", "spawn_dict"), now=now, default={}) or {}
        spawn_dict = _spawn_dict_from_names(spawn_dict_raw)

        if hold_for_reserve:
            if self.log is not None and (int(tick.iteration) % self.log_every_iters == 0):
                self.log.emit(
                    "macro_production",
                    {
                        "iter": int(tick.iteration),
                        "t": round(float(now), 2),
                        "action": "planner_reserve_hold",
                        "reserve_minerals": int(reserve_m),
                        "reserve_gas": int(reserve_g),
                        "minerals": int(attention.economy.minerals),
                        "gas": int(attention.economy.gas),
                        "morph_reserve_minerals": int(morph_reserve_m),
                        "morph_reserve_gas": int(morph_reserve_g),
                        "tech_reserve_minerals": int(tech_reserve_m),
                        "tech_reserve_gas": int(tech_reserve_g),
                        "reserve_tech_name": str(reserve_tech_name),
                        "reserve_spending_name": str(reserve_spending_name),
                        "spending_reserve_minerals": int(spending_reserve_m),
                        "spending_reserve_gas": int(spending_reserve_g),
                    },
                )
            return TaskResult.running("production_reserved_by_plan")

        plan = MacroPlan()
        if workers_enabled:
            plan.add(BuildWorkers(to_count=int(dynamic_scv_cap)))
        plan.add(
            SpawnController(
                army_composition_dict=spawn_dict,
                freeflow_mode=bool(freeflow_mode),
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
                    "workers_enabled": bool(workers_enabled),
                    "units": [u.name for u in spawn_dict.keys()],
                    "freeflow_mode": bool(freeflow_mode),
                    "reserve_minerals": int(reserve_m),
                    "reserve_gas": int(reserve_g),
                    "morph_reserve_minerals": int(morph_reserve_m),
                    "morph_reserve_gas": int(morph_reserve_g),
                    "tech_reserve_minerals": int(tech_reserve_m),
                    "tech_reserve_gas": int(tech_reserve_g),
                    "reserve_tech_name": str(reserve_tech_name),
                    "reserve_spending_name": str(reserve_spending_name),
                    "spending_reserve_minerals": int(spending_reserve_m),
                    "spending_reserve_gas": int(spending_reserve_g),
                    "rush_state": str(rush_state),
                    "parity_overall": str(parity_overall),
                    "parity_econ": str(parity_econ),
                    "parity_army": str(parity_army),
                },
            )

        if not workers_enabled:
            return TaskResult.running("production_plan_registered_orbital_priority")
        return TaskResult.running("production_plan_registered")

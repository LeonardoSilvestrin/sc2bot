from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.utils.base_planner import BasePlanner
from bot.planners.utils.proposals import Proposal, TaskSpec
from bot.tasks.macro.production_tick import MacroProductionTick
from bot.tasks.macro.utils.desired_comp import desired_controller_dict_names


@dataclass
class ProductionPlanner(BasePlanner):
    """
    Planner decides production policy and publishes an explicit execution plan.
    Task only executes this plan.
    """

    planner_id: str = "production_planner"
    score: int = 55
    log: DevLogger | None = None

    scv_cap: int = 66
    log_every_iters: int = 22
    plan_ttl_s: float = 8.0

    def _pid(self) -> str:
        return self.proposal_id("macro_production")

    @staticmethod
    def _rush_state(*, awareness: Awareness, now: float) -> str:
        return str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()

    @staticmethod
    def _is_rush_active(state: str) -> bool:
        return str(state).upper() in {"SUSPECTED", "CONFIRMED", "HOLDING"}

    @staticmethod
    def _parity_signal(*, awareness: Awareness, now: float) -> tuple[str, str, str, int, int]:
        overall = str(awareness.mem.get(K("strategy", "parity", "overall"), now=now, default="EVEN") or "EVEN")
        econ = str(awareness.mem.get(K("strategy", "parity", "econ"), now=now, default="EVEN") or "EVEN")
        army = str(awareness.mem.get(K("strategy", "parity", "army"), now=now, default="EVEN") or "EVEN")
        expand_bias = int(awareness.mem.get(K("strategy", "parity", "expand_bias"), now=now, default=0) or 0)
        army_bias = int(awareness.mem.get(K("strategy", "parity", "army_bias"), now=now, default=0) or 0)
        return overall, econ, army, expand_bias, army_bias

    @staticmethod
    def _spawn_dict_names(*, awareness: Awareness, now: float) -> dict[str, dict[str, float | int]]:
        return desired_controller_dict_names(awareness=awareness, now=now)

    def _publish_production_plan(self, bot, *, awareness: Awareness, attention: Attention, now: float) -> None:
        rush_state = self._rush_state(awareness=awareness, now=now)
        rush_active = self._is_rush_active(rush_state)
        parity_overall, parity_econ, parity_army, expand_bias, army_bias = self._parity_signal(awareness=awareness, now=now)

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

        spawn_dict_names = self._spawn_dict_names(awareness=awareness, now=now)
        ttl = float(self.plan_ttl_s)
        awareness.mem.set(K("macro", "production", "plan", "workers_enabled"), value=bool(allow_worker_production), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "production", "plan", "dynamic_scv_cap"), value=int(dynamic_scv_cap), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "production", "plan", "freeflow_mode"), value=bool(attention.economy.minerals >= int(freeflow_threshold)), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "production", "plan", "spawn_dict"), value=dict(spawn_dict_names), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "production", "plan", "parity_overall"), value=str(parity_overall), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "production", "plan", "parity_econ"), value=str(parity_econ), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "production", "plan", "parity_army"), value=str(parity_army), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "production", "plan", "rush_state"), value=str(rush_state), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "production", "plan", "updated_at"), value=float(now), now=now, ttl=None)

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)
        self._publish_production_plan(bot, awareness=awareness, attention=attention, now=now)

        pid = self._pid()
        if self.is_proposal_running(awareness=awareness, proposal_id=pid, now=now):
            return []

        def _factory(mission_id: str) -> MacroProductionTick:
            return MacroProductionTick(awareness=awareness, log=self.log, scv_cap=int(self.scv_cap), log_every_iters=int(self.log_every_iters))

        out = self.make_single_task_proposal(
            proposal_id=pid,
            domain="MACRO_PRODUCTION",
            score=int(self.score),
            task_spec=TaskSpec(task_id="macro_production", task_factory=_factory, unit_requirements=[]),
            lease_ttl=None,
            cooldown_s=0.0,
            risk_level=0,
            allow_preempt=True,
        )

        self.emit_planner_proposed({"count": len(out), "mode": "production"})
        return out

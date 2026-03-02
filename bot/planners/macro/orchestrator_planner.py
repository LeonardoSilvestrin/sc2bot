from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.utils.base_planner import BasePlanner
from bot.planners.utils.proposals import Proposal, TaskSpec
from bot.tasks.macro.tasks.macro_ares_executor_tick import MacroAresExecutorTick
from bot.tasks.macro.tasks.scv_housekeeping_task import ScvHousekeeping
from bot.tasks.support.control_depots_task import ControlDepots
from bot.tasks.tech.tasks.tech_ares_executor_tick import TechAresExecutorTick


@dataclass
class MacroOrchestratorPlanner(BasePlanner):
    planner_id: str = "macro_orchestrator_planner"
    score: int = 58
    planners: list[Any] = None
    log: DevLogger | None = None
    log_every_iters: int = 22

    executor_score: int = 60
    exec_min_interval_s: float = 1.2
    tech_executor_score: int = 44
    tech_exec_min_interval_s: float = 1.2
    critical_expand_cooldown_s: float = 12.0
    critical_gas_cooldown_s: float = 10.0

    phase_opening_max_s: float = 220.0
    phase_late_after_s: float = 620.0
    phase_late_bases: int = 4

    pressure_urgency_high: int = 18
    pressure_enemy_count_high: int = 3

    freeflow_on_minerals: int = 1200
    freeflow_off_minerals: int = 700
    freeflow_hold_s: float = 8.0

    scv_cap_opening: int = 50
    scv_cap_mid: int = 66
    scv_cap_late: int = 78

    opening_gas_cap: int = 2
    late_gas_bonus: int = 2

    housekeeping_score: int = 18
    housekeeping_interval_s: float = 4.0
    housekeeping_cooldown_s: float = 2.0
    housekeeping_lease_ttl_s: float = 6.0

    depot_score: int = 24
    depot_interval_s_alert: float = 2.5
    depot_interval_s_calm: float = 6.0
    depot_cooldown_s: float = 2.0
    depot_raise_radius: float = 12.0
    depot_raise_urgency_min: int = 18
    depot_raise_enemy_count_min: int = 2
    depot_supply_left_trigger: int = 2

    _last_exec_publish_at: float = -9999.0
    _last_tech_exec_publish_at: float = -9999.0

    def _phase(self, *, attention: Attention, now: float) -> str:
        if not bool(attention.macro.opening_done) and float(now) <= float(self.phase_opening_max_s):
            return "OPENING"
        if int(attention.macro.bases_total) >= int(self.phase_late_bases) or float(now) >= float(self.phase_late_after_s):
            return "LATE"
        return "MID"

    def _pressure_high(self, *, awareness: Awareness, attention: Attention, now: float) -> bool:
        rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        return bool(
            int(attention.combat.primary_urgency) >= int(self.pressure_urgency_high)
            or int(attention.combat.primary_enemy_count) >= int(self.pressure_enemy_count_high)
            or rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}
        )

    def _freeflow_hysteresis(self, *, awareness: Awareness, now: float, minerals: int, pressure_high: bool) -> bool:
        if pressure_high:
            awareness.mem.set(K("macro", "exec", "freeflow_state"), value=False, now=now, ttl=20.0)
            awareness.mem.set(K("macro", "exec", "freeflow_pending_since"), value=0.0, now=now, ttl=20.0)
            return False

        state = bool(awareness.mem.get(K("macro", "exec", "freeflow_state"), now=now, default=False))
        pending_since = float(awareness.mem.get(K("macro", "exec", "freeflow_pending_since"), now=now, default=0.0) or 0.0)
        target_state = state
        if state:
            target_state = bool(int(minerals) > int(self.freeflow_off_minerals))
        else:
            target_state = bool(int(minerals) >= int(self.freeflow_on_minerals))

        if target_state == state:
            awareness.mem.set(K("macro", "exec", "freeflow_pending_since"), value=0.0, now=now, ttl=20.0)
            return state

        if pending_since <= 0.0:
            awareness.mem.set(K("macro", "exec", "freeflow_pending_since"), value=float(now), now=now, ttl=20.0)
            return state
        if (float(now) - float(pending_since)) < float(self.freeflow_hold_s):
            return state

        awareness.mem.set(K("macro", "exec", "freeflow_state"), value=bool(target_state), now=now, ttl=20.0)
        awareness.mem.set(K("macro", "exec", "freeflow_pending_since"), value=0.0, now=now, ttl=20.0)
        return bool(target_state)

    def _cooldown_value(
        self,
        *,
        awareness: Awareness,
        now: float,
        key: tuple[str, ...],
        changed_key: tuple[str, ...],
        proposed: int,
        cooldown_s: float,
    ) -> int:
        prev = awareness.mem.get(key, now=now, default=None)
        prev_i = int(prev) if isinstance(prev, (int, float)) else None
        if prev_i is None or int(proposed) == int(prev_i):
            return int(proposed)
        last_changed = float(awareness.mem.get(changed_key, now=now, default=-9999.0) or -9999.0)
        if (float(now) - float(last_changed)) >= float(cooldown_s):
            awareness.mem.set(changed_key, value=float(now), now=now, ttl=30.0)
            return int(proposed)
        return int(prev_i)

    def _publish_exec(self, bot, *, awareness: Awareness, attention: Attention, now: float) -> None:
        phase = self._phase(attention=attention, now=now)
        pressure_high = self._pressure_high(awareness=awareness, attention=attention, now=now)
        bases_now = int(attention.macro.bases_total)
        pending_cc = int(bot.already_pending(U.COMMANDCENTER) or 0)
        total_bases = int(bases_now + pending_cc)

        if phase == "OPENING":
            scv_cap = int(self.scv_cap_opening)
            base_expand = 2
        elif phase == "LATE":
            scv_cap = int(self.scv_cap_late)
            base_expand = max(4, int(total_bases) + 1)
        else:
            scv_cap = int(self.scv_cap_mid)
            base_expand = max(2, int(total_bases) + 1)

        if pressure_high:
            scv_cap = max(30, int(scv_cap) - 8)
            base_expand = min(int(base_expand), int(total_bases))

        gas_target = max(0, int(bases_now) * 2)
        if phase == "OPENING":
            gas_target = min(int(gas_target), int(self.opening_gas_cap))
        elif phase == "LATE" and not pressure_high:
            gas_target += int(self.late_gas_bonus)

        freeflow_mode = self._freeflow_hysteresis(
            awareness=awareness,
            now=now,
            minerals=int(attention.economy.minerals),
            pressure_high=bool(pressure_high),
        )
        if phase == "OPENING":
            freeflow_mode = False

        expand_to = self._cooldown_value(
            awareness=awareness,
            now=now,
            key=K("macro", "exec", "expand_to"),
            changed_key=K("macro", "exec", "changed_at_expand_to"),
            proposed=max(1, int(base_expand)),
            cooldown_s=float(self.critical_expand_cooldown_s),
        )
        gas_target = self._cooldown_value(
            awareness=awareness,
            now=now,
            key=K("macro", "exec", "gas_target"),
            changed_key=K("macro", "exec", "changed_at_gas_target"),
            proposed=max(0, int(gas_target)),
            cooldown_s=float(self.critical_gas_cooldown_s),
        )

        enable_workers = bool(not pressure_high or int(attention.economy.workers_total) < 32)
        enable_expansion = bool(not pressure_high)
        if phase == "OPENING" and int(total_bases) < 2:
            enable_expansion = True

        ttl = 12.0
        awareness.mem.set(K("control", "phase"), value=str(phase), now=now, ttl=ttl)
        awareness.mem.set(K("control", "pressure", "level"), value=3 if pressure_high else 1, now=now, ttl=ttl)
        awareness.mem.set(K("control", "pressure", "threat_pos"), value=attention.combat.primary_threat_pos, now=now, ttl=ttl)

        awareness.mem.set(K("macro", "exec", "enable_workers"), value=bool(enable_workers), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "scv_cap"), value=int(scv_cap), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enable_supply"), value=True, now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enable_gas"), value=True, now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "gas_target"), value=int(gas_target), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enable_spawn"), value=True, now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "freeflow_mode"), value=bool(freeflow_mode), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enable_production"), value=True, now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enable_expansion"), value=bool(enable_expansion), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "expand_to"), value=int(expand_to), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "cooldown_until"), value=0.0, now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "owner"), value=str(self.planner_id), now=now, ttl=ttl)

    def _publish_tech_exec(self, bot, *, awareness: Awareness, attention: Attention, now: float) -> None:
        bor = getattr(bot, "build_order_runner", None)
        opening_active = bool(bor is not None and not bool(getattr(bor, "build_completed", False)))
        desired_targets = awareness.mem.get(K("macro", "desired", "tech_targets"), now=now, default={}) or {}
        if not isinstance(desired_targets, dict):
            desired_targets = {}
        upgrades = list(desired_targets.get("upgrades", [])) if isinstance(desired_targets.get("upgrades", []), list) else []
        structures = dict(desired_targets.get("structures", {})) if isinstance(desired_targets.get("structures", {}), dict) else {}
        enable = bool((not opening_active) and (bool(upgrades) or bool(structures)))

        ttl = 12.0
        awareness.mem.set(K("tech", "exec", "enable"), value=bool(enable), now=now, ttl=ttl)
        awareness.mem.set(
            K("tech", "exec", "targets"),
            value={"upgrades": list(upgrades), "structures": dict(structures)},
            now=now,
            ttl=ttl,
        )
        awareness.mem.set(K("tech", "exec", "cooldown_until"), value=0.0, now=now, ttl=ttl)
        awareness.mem.set(K("tech", "exec", "owner"), value=str(self.planner_id), now=now, ttl=ttl)

    def _make_domain_proposals(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)
        out: list[Proposal] = []

        if (float(now) - float(self._last_exec_publish_at)) >= max(0.2, float(self.exec_min_interval_s)):
            self._publish_exec(bot, awareness=awareness, attention=attention, now=now)
            self._last_exec_publish_at = float(now)
        if (float(now) - float(self._last_tech_exec_publish_at)) >= max(0.2, float(self.tech_exec_min_interval_s)):
            self._publish_tech_exec(bot, awareness=awareness, attention=attention, now=now)
            self._last_tech_exec_publish_at = float(now)

        executor_pid = self.proposal_id("macro_ares_executor")
        if not self.is_proposal_running(awareness=awareness, proposal_id=executor_pid, now=now):

            def _executor_factory(mission_id: str) -> MacroAresExecutorTick:
                return MacroAresExecutorTick(
                    awareness=awareness,
                    log=self.log,
                    log_every_iters=int(self.log_every_iters),
                )

            out.extend(
                self.make_single_task_proposal(
                    proposal_id=executor_pid,
                    domain="MACRO_EXECUTOR",
                    score=int(self.executor_score),
                    task_spec=TaskSpec(task_id="macro_ares_executor", task_factory=_executor_factory, unit_requirements=[]),
                    lease_ttl=None,
                    cooldown_s=0.0,
                    risk_level=0,
                    allow_preempt=True,
                )
            )

        tech_executor_pid = self.proposal_id("tech_ares_executor")
        if not self.is_proposal_running(awareness=awareness, proposal_id=tech_executor_pid, now=now):
            tech_enable = bool(awareness.mem.get(K("tech", "exec", "enable"), now=now, default=False))
            if tech_enable:

                def _tech_executor_factory(mission_id: str) -> TechAresExecutorTick:
                    return TechAresExecutorTick(
                        awareness=awareness,
                        log=self.log,
                    )

                out.extend(
                    self.make_single_task_proposal(
                        proposal_id=tech_executor_pid,
                        domain="TECH_EXECUTOR",
                        score=int(self.tech_executor_score),
                        task_spec=TaskSpec(task_id="tech_ares_executor", task_factory=_tech_executor_factory, unit_requirements=[]),
                        lease_ttl=None,
                        cooldown_s=0.0,
                        risk_level=0,
                        allow_preempt=True,
                    )
                )

        housekeeping_pid = self.proposal_id("scv_housekeeping")
        due_housekeeping = self.due_by_last_done(
            awareness=awareness,
            key=K("ops", "macro", "scv", "housekeeping", "last_done_at"),
            now=now,
            interval_s=float(self.housekeeping_interval_s),
        )
        if due_housekeeping and not self.is_proposal_running(awareness=awareness, proposal_id=housekeeping_pid, now=now):

            def _housekeeping_factory(mission_id: str) -> ScvHousekeeping:
                return ScvHousekeeping(awareness=awareness)

            out.extend(
                self.make_single_task_proposal(
                    proposal_id=housekeeping_pid,
                    domain="MACRO_HOUSEKEEPING",
                    score=int(self.housekeeping_score),
                    task_spec=TaskSpec(task_id="scv_housekeeping", task_factory=_housekeeping_factory, unit_requirements=[]),
                    lease_ttl=float(self.housekeeping_lease_ttl_s),
                    cooldown_s=float(self.housekeeping_cooldown_s),
                    risk_level=0,
                    allow_preempt=True,
                )
            )

        depot_pid = self.proposal_id("control_depots")
        supply_left = int(attention.economy.supply_left)
        urgency = int(attention.combat.primary_urgency)
        enemy_count = int(attention.combat.primary_enemy_count)
        depot_alert = bool(
            (urgency >= int(self.depot_raise_urgency_min) and enemy_count >= int(self.depot_raise_enemy_count_min))
            or supply_left <= int(self.depot_supply_left_trigger)
        )
        depot_interval = float(self.depot_interval_s_alert if depot_alert else self.depot_interval_s_calm)
        due_depot = self.due_by_last_done(
            awareness=awareness,
            key=K("ops", "macro", "wall", "depot_control", "last_done_at"),
            now=now,
            interval_s=float(depot_interval),
        )
        if due_depot and not self.is_proposal_running(awareness=awareness, proposal_id=depot_pid, now=now):
            threat_pos = attention.combat.primary_threat_pos
            actionable = False
            try:
                if depot_alert:
                    if threat_pos is not None:
                        lowered = bot.structures.of_type({U.SUPPLYDEPOTLOWERED}).ready
                        actionable = any(float(d.distance_to(threat_pos)) <= float(self.depot_raise_radius) for d in lowered)
                else:
                    raised = int(bot.structures.of_type({U.SUPPLYDEPOT}).ready.amount)
                    actionable = int(raised) > 0
            except Exception:
                actionable = False
            if not actionable:
                return out
            score = int(self.depot_score) + min(30, max(0, urgency // 2))

            def _depot_factory(mission_id: str) -> ControlDepots:
                return ControlDepots(
                    awareness=awareness,
                    threat_pos=threat_pos,
                    raise_radius=float(self.depot_raise_radius),
                    raise_urgency_min=int(self.depot_raise_urgency_min),
                    raise_enemy_count_min=int(self.depot_raise_enemy_count_min),
                )

            out.extend(
                self.make_single_task_proposal(
                    proposal_id=depot_pid,
                    domain="MACRO_DEPOT_CONTROL",
                    score=int(score),
                    task_spec=TaskSpec(task_id="control_depots", task_factory=_depot_factory, unit_requirements=[]),
                    lease_ttl=None,
                    cooldown_s=float(self.depot_cooldown_s),
                    risk_level=0,
                    allow_preempt=True,
                )
            )

        return out

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        domain_proposals = self._make_domain_proposals(bot, awareness=awareness, attention=attention)
        if domain_proposals:
            self.emit_planner_proposed({"count": len(domain_proposals), "children": int(len(self.planners or []))})
        return domain_proposals

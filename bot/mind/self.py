# bot/mind/self.py
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ares.behaviors.macro.mining import Mining
from sc2.data import Result

from bot.devlog import DevLogger
from bot.sensors.threat_sensor import Threat
from bot.intel.enemy_build_intel import EnemyBuildIntelConfig, derive_enemy_build_intel
from bot.intel.game_parity_intel import GameParityIntelConfig, derive_game_parity_intel
from bot.intel.my_army_composition_intel import MyArmyCompositionConfig, derive_my_army_composition_intel
from bot.intel.opening_intel import OpeningIntelConfig, derive_enemy_opening_intel
from bot.intel.opening_contract_intel import derive_opening_contract_intel
from bot.mind.attention import derive_attention
from bot.mind.awareness import Awareness, K
from bot.mind.body import UnitLeases
from bot.mind.ego import Ego, EgoConfig
from bot.tasks.base_task import TaskTick

from bot.tasks.defense.defend_task import Defend
from bot.tasks.macro.tasks.opening import MacroOpeningTick

from bot.planners.defense_planner import DefensePlanner
from bot.planners.harass_planner import HarassPlanner
from bot.planners.housekeeping_planner import HousekeepingPlanner
from bot.planners.intel_planner import IntelPlanner

from bot.planners.macro_orchestrator_planner import MacroOrchestratorPlanner


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Enum):
        return str(value.name)

    if is_dataclass(value):
        return _jsonable(asdict(value))

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out[str(k)] = _jsonable(v)
        return out

    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]

    if hasattr(value, "x") and hasattr(value, "y"):
        try:
            return {"x": float(getattr(value, "x")), "y": float(getattr(value, "y"))}
        except Exception:
            return str(value)

    return str(value)


@dataclass
class RuntimeApp:
    log: DevLogger
    awareness: Awareness
    threat: Threat
    body: UnitLeases
    ego: Ego
    enemy_build_cfg: EnemyBuildIntelConfig
    opening_cfg: OpeningIntelConfig
    my_comp_cfg: MyArmyCompositionConfig
    parity_cfg: GameParityIntelConfig
    debug: bool = True
    attention_full_every_iters: int = 25
    awareness_full_every_iters: int = 50
    full_snapshots_default: bool = False
    full_snapshots_flag_path: str = "_prompt/full_snapshots.flag"
    bo_diag_every_iters: int = 25
    bo_stall_warn_s: float = 25.0
    runtime_clock_every_iters: int = 24
    runtime_clock_print: bool = False
    _bo_last_step_idx: int = -1
    _bo_last_step_t: float = 0.0
    _bo_last_opening: str = ""
    _chat_last_opening: str = ""
    _chat_last_transition: str = ""
    _chat_last_enemy_kind: str = ""
    _chat_last_rush_state: str = ""
    _chat_last_aggression_state: str = ""
    _chat_seen_early_rush: bool = False
    _chat_rush_held_announced: bool = False
    _chat_last_sent_t: float = -9999.0
    chat_enabled: bool = True
    chat_min_interval_s: float = 10.0
    _wall_start_s: float = 0.0

    @classmethod
    def build(cls, *, log: DevLogger, debug: bool = True) -> "RuntimeApp":
        awareness = Awareness(log=log)
        threat = Threat(defend_radius=22.0, min_enemy=1)
        body = UnitLeases(default_ttl=8.0)

        ego = Ego(
            body=body,
            log=log,
            cfg=EgoConfig(
                # Singleton macro domains after macro executor unification.
                singleton_domains=frozenset(
                    {
                        "MACRO_EXECUTOR",
                        "MACRO_ARMY_EXECUTOR",
                        "MACRO_ECON_EXECUTOR",
                        "TECH_EXECUTOR",
                        "MACRO_HOUSEKEEPING",
                        "MACRO_DEPOT_CONTROL",
                    }
                ),
                threat_block_start_at=70,
                threat_force_preempt_at=90,
                non_preemptible_grace_s=2.5,
                default_failure_cooldown_s=8.0,
            ),
        )

        defend_task = Defend(log=log, log_every_iters=11)

        # Opening remains a tiny SCV-only macro while BuildRunner/YML does the rest.
        opening_macro_task = MacroOpeningTick(log=log, log_every_iters=22, scv_cap=60)

        defense_planner = DefensePlanner(defend_task=defend_task, log=log)
        harass_planner = HarassPlanner(log=log)
        intel_planner = IntelPlanner(awareness=awareness, log=log)
        housekeeping_planner = HousekeepingPlanner(log=log)
        macro_orchestrator_planner = MacroOrchestratorPlanner(log=log)

        # Keep opening as a "pre-macro" handled by its own planner.
        # For now: register opening via a tiny planner-inline shim inside runtime:
        # We keep it as a planner to respect the architecture.
        from bot.planners.utils.proposals import Proposal, TaskSpec

        @dataclass
        class OpeningPlanner:
            planner_id: str = "opening_planner"
            score: int = 60
            log: DevLogger | None = None
            opening_task: MacroOpeningTick = None

            def _pid(self) -> str:
                return f"{self.planner_id}:macro_opening"

            def propose(self, bot, *, awareness: Awareness, attention) -> list[Proposal]:
                now = float(attention.time)
                # If BuildOrderRunner exists, let it own opening execution.
                if getattr(bot, "build_order_runner", None) is not None:
                    return []
                if bool(attention.macro.opening_done):
                    return []
                pid = self._pid()
                if awareness.ops_proposal_running(proposal_id=pid, now=now):
                    return []

                def _factory(mission_id: str) -> MacroOpeningTick:
                    return self.opening_task.spawn()

                out = [
                    Proposal(
                        proposal_id=pid,
                        domain="MACRO_EXECUTOR",  # opening shares the single macro executor lane
                        score=int(self.score),
                        tasks=[TaskSpec(task_id="macro_opening", task_factory=_factory, unit_requirements=[], lease_ttl=None)],
                        lease_ttl=None,
                        cooldown_s=0.0,
                        risk_level=0,
                        allow_preempt=True,
                    )
                ]
                if self.log:
                    self.log.emit(
                        "planner_proposed",
                        {"planner": self.planner_id, "count": len(out), "mode": "opening"},
                        meta={"module": "planner", "component": f"planner.{self.planner_id}"},
                    )
                return out

        opening_planner = OpeningPlanner(opening_task=opening_macro_task, log=log)

        ego.register_planners(
            [
                defense_planner,
                harass_planner,
                intel_planner,
                housekeeping_planner,
                opening_planner,
                macro_orchestrator_planner,
            ]
        )

        return cls(
            log=log,
            awareness=awareness,
            threat=threat,
            body=body,
            ego=ego,
            enemy_build_cfg=EnemyBuildIntelConfig(),
            opening_cfg=OpeningIntelConfig(),
            my_comp_cfg=MyArmyCompositionConfig(),
            parity_cfg=GameParityIntelConfig(),
            debug=bool(debug),
        )

    async def on_start(self, bot) -> None:
        import time
        try:
            self.body.reset()
        except Exception:
            pass
        self._chat_last_enemy_kind = ""
        self._chat_last_rush_state = ""
        self._chat_last_aggression_state = ""
        self._chat_seen_early_rush = False
        self._chat_rush_held_announced = False
        self._wall_start_s = float(time.perf_counter())
        derive_opening_contract_intel(
            bot,
            awareness=self.awareness,
            now=float(getattr(bot, "time", 0.0) or 0.0),
        )
        if self.log:
            self.log.emit("runtime_start", {})

    async def on_step(self, bot, *, iteration: int) -> None:
        now = float(getattr(bot, "time", 0.0))
        # Keep Ares resource-manager bookkeeping actively applied each frame.
        bot.register_behavior(Mining())
        derive_opening_contract_intel(bot, awareness=self.awareness, now=now)

        attention = derive_attention(bot, awareness=self.awareness, threat=self.threat, log=self.log)

        derive_enemy_opening_intel(
            bot,
            awareness=self.awareness,
            attention=attention,
            now=now,
            cfg=self.opening_cfg,
        )
        derive_enemy_build_intel(
            bot,
            awareness=self.awareness,
            attention=attention,
            now=now,
            cfg=self.enemy_build_cfg,
        )

        # New: strategy reference (mode + proportions)
        derive_my_army_composition_intel(
            awareness=self.awareness,
            attention=attention,
            now=now,
            cfg=self.my_comp_cfg,
        )
        derive_game_parity_intel(
            bot,
            awareness=self.awareness,
            attention=attention,
            now=now,
            cfg=self.parity_cfg,
        )
        await self._emit_chat_updates(bot, now=now)

        self._emit_build_order_diagnostics(bot, now=now, iteration=int(iteration))

        if self.log and self._full_snapshots_enabled():
            if int(iteration) % max(1, int(self.attention_full_every_iters)) == 0:
                self.log.emit(
                    "attention_full",
                    _jsonable(attention),
                    meta={"module": "attention", "component": "attention.full"},
                )
            if int(iteration) % max(1, int(self.awareness_full_every_iters)) == 0:
                self.log.emit(
                    "awareness_full",
                    {
                        "mem": _jsonable(self.awareness.mem.snapshot(now=now)),
                        "events_tail": _jsonable(self.awareness.tail_events(80)),
                    },
                    meta={"module": "awareness", "component": "awareness.full"},
                )

        tick = TaskTick(iteration=int(iteration), time=now)
        await self.ego.tick(bot, tick=tick, attention=attention, awareness=self.awareness)
        self._emit_runtime_clock(iteration=int(iteration), now=now)

    async def on_end(self, bot, game_result: Result) -> None:
        if self.log:
            self.log.emit("game_end", {"result": str(game_result)})

    def _full_snapshots_enabled(self) -> bool:
        if bool(self.full_snapshots_default):
            return True

        # Optional runtime override: set FULL_SNAPSHOTS=1/true/on.
        try:
            import os

            env = str(os.getenv("FULL_SNAPSHOTS", "")).strip().lower()
            if env in {"1", "true", "on", "yes"}:
                return True
        except Exception:
            pass

        # Accept both CWD-relative and repo-root-relative flag paths.
        try:
            rel = Path(self.full_snapshots_flag_path)
            if rel.exists():
                return True

            repo_root = Path(__file__).resolve().parents[2]
            if (repo_root / rel).exists():
                return True
        except Exception:
            return False

        return False

    def _emit_build_order_diagnostics(self, bot, *, now: float, iteration: int) -> None:
        if self.log is None:
            return

        bor = getattr(bot, "build_order_runner", None)
        if bor is None:
            return

        build_order = list(getattr(bor, "build_order", []) or [])
        total_steps = len(build_order)
        step_idx = int(getattr(bor, "build_step", 0) or 0)
        temp_step_idx = int(getattr(bor, "_temporary_build_step", -1) or -1)
        build_completed = bool(getattr(bor, "build_completed", False))
        chosen_opening = str(getattr(bor, "chosen_opening", ""))
        current_step_started = bool(getattr(bor, "current_step_started", False))
        current_step_complete = bool(getattr(bor, "current_step_complete", False))

        if chosen_opening and str(chosen_opening) != str(self._bo_last_opening):
            self._bo_last_opening = str(chosen_opening)
            self.log.emit(
                "build_order_selected",
                {
                    "iter": int(iteration),
                    "t": round(float(now), 2),
                    "chosen_opening": str(chosen_opening),
                },
                meta={"module": "macro", "component": "build_order.runner"},
            )

        if step_idx != self._bo_last_step_idx:
            self._bo_last_step_idx = int(step_idx)
            self._bo_last_step_t = float(now)
        stall_s = max(0.0, float(now) - float(self._bo_last_step_t))

        command_name = ""
        start_at_supply = None
        target = None
        start_condition_ok = None
        end_condition_ok = None
        blocked_reason = ""

        if 0 <= step_idx < total_steps:
            step = build_order[step_idx]
            command_name = getattr(step.command, "name", str(step.command))
            start_at_supply = int(getattr(step, "start_at_supply", 0) or 0)
            target = _jsonable(getattr(step, "target", None))
            try:
                start_condition_ok = bool(step.start_condition())
            except Exception as e:
                start_condition_ok = f"error:{type(e).__name__}"
            try:
                end_condition_ok = bool(step.end_condition())
            except Exception as e:
                end_condition_ok = f"error:{type(e).__name__}"

            # Lightweight explainability for why current step is not advancing.
            if not bool(build_completed) and not blocked_reason:
                if not bool(current_step_started):
                    if int(getattr(bot, "supply_used", 0.0) or 0.0) < int(start_at_supply or 0):
                        blocked_reason = f"waiting_supply:{int(getattr(bot, 'supply_used', 0.0) or 0)}/{int(start_at_supply or 0)}"
                    elif isinstance(start_condition_ok, str):
                        blocked_reason = f"start_condition_{start_condition_ok}"
                    elif start_condition_ok is False:
                        blocked_reason = "start_condition_false"
                elif bool(current_step_started) and not bool(current_step_complete):
                    if isinstance(end_condition_ok, str):
                        blocked_reason = f"end_condition_{end_condition_ok}"
                    elif end_condition_ok is False:
                        blocked_reason = "waiting_end_condition"
                if not blocked_reason:
                    blocked_reason = "progressing"

        if int(iteration) % max(1, int(self.bo_diag_every_iters)) == 0:
            self.log.emit(
                "build_order_status",
                {
                    "iter": int(iteration),
                    "t": round(float(now), 2),
                    "chosen_opening": chosen_opening,
                    "build_completed": bool(build_completed),
                    "step_idx": int(step_idx),
                    "total_steps": int(total_steps),
                    "temp_step_idx": int(temp_step_idx),
                    "current_step_started": bool(current_step_started),
                    "current_step_complete": bool(current_step_complete),
                    "command": command_name,
                    "start_at_supply": start_at_supply,
                    "target": target,
                    "start_condition_ok": start_condition_ok,
                    "end_condition_ok": end_condition_ok,
                    "blocked_reason": str(blocked_reason),
                    "supply_used": float(getattr(bot, "supply_used", 0.0) or 0.0),
                    "minerals": int(getattr(bot, "minerals", 0) or 0),
                    "vespene": int(getattr(bot, "vespene", 0) or 0),
                    "stall_s_on_step": round(float(stall_s), 2),
                },
                meta={"module": "macro", "component": "build_order.runner"},
            )
        if (
            not build_completed
            and total_steps > 0
            and stall_s >= float(self.bo_stall_warn_s)
            and int(iteration) % max(1, int(self.bo_diag_every_iters)) == 0
        ):
            self.log.emit(
                "build_order_stall",
                {
                    "iter": int(iteration),
                    "t": round(float(now), 2),
                    "chosen_opening": chosen_opening,
                    "step_idx": int(step_idx),
                    "total_steps": int(total_steps),
                    "command": command_name,
                    "start_at_supply": start_at_supply,
                    "start_condition_ok": start_condition_ok,
                    "end_condition_ok": end_condition_ok,
                    "blocked_reason": str(blocked_reason),
                    "current_step_started": bool(current_step_started),
                    "current_step_complete": bool(current_step_complete),
                    "stall_s_on_step": round(float(stall_s), 2),
                },
                meta={"module": "macro", "component": "build_order.runner"},
            )

    def _emit_runtime_clock(self, *, iteration: int, now: float) -> None:
        if self.log is None:
            return
        if int(iteration) % max(1, int(self.runtime_clock_every_iters)) != 0:
            return
        import time

        wall_elapsed = max(1e-6, float(time.perf_counter()) - float(self._wall_start_s))
        speed_x = float(now) / float(wall_elapsed)
        lag_prod = float(self.awareness.mem.get(K("control", "priority", "lag", "production"), now=now, default=0.0) or 0.0)
        lag_construction = float(
            self.awareness.mem.get(K("control", "priority", "lag", "construction"), now=now, default=0.0) or 0.0
        )
        lag_spend = float(self.awareness.mem.get(K("control", "priority", "lag", "spending"), now=now, default=0.0) or 0.0)
        lag_tech = float(self.awareness.mem.get(K("control", "priority", "lag", "tech"), now=now, default=0.0) or 0.0)
        lag_army = float(self.awareness.mem.get(K("control", "priority", "lag", "army_supply"), now=now, default=0.0) or 0.0)
        macro_plan_version = int(self.awareness.mem.get(K("macro", "plan", "version"), now=now, default=0) or 0)
        macro_budget_enabled = bool(self.awareness.mem.get(K("ego", "exec_budget", "macro_enabled"), now=now, default=True))
        macro_budget_reason = str(self.awareness.mem.get(K("ego", "exec_budget", "macro_reason"), now=now, default="normal") or "normal")
        bank_pi_output = float(self.awareness.mem.get(K("control", "priority", "bank_pi_output"), now=now, default=0.0) or 0.0)
        parity_state = str(
            self.awareness.mem.get(K("strategy", "parity", "state"), now=now, default="TRADEOFF_MIXED")
            or "TRADEOFF_MIXED"
        )
        parity_army_behind = float(
            self.awareness.mem.get(K("strategy", "parity", "severity", "army_behind"), now=now, default=0.0) or 0.0
        )
        parity_econ_behind = float(
            self.awareness.mem.get(K("strategy", "parity", "severity", "econ_behind"), now=now, default=0.0) or 0.0
        )
        rush_state = str(self.awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        payload = {
            "iter": int(iteration),
            "game_t": round(float(now), 2),
            "wall_t": round(float(wall_elapsed), 2),
            "speed_x": round(float(speed_x), 3),
            "lag_production": round(float(lag_prod), 3),
            "lag_construction": round(float(lag_construction), 3),
            "lag_spending": round(float(lag_spend), 3),
            "lag_tech": round(float(lag_tech), 3),
            "lag_army_supply": round(float(lag_army), 3),
            "macro_plan_version": int(macro_plan_version),
            "macro_budget_enabled": bool(macro_budget_enabled),
            "macro_budget_reason": str(macro_budget_reason),
            "bank_pi_output": round(float(bank_pi_output), 3),
            "parity_state": str(parity_state),
            "parity_army_behind": round(float(parity_army_behind), 3),
            "parity_econ_behind": round(float(parity_econ_behind), 3),
            "rush_state": str(rush_state),
        }
        self.log.emit(
            "runtime_clock",
            payload,
            meta={"module": "runtime", "component": "runtime.clock"},
        )
        if bool(self.runtime_clock_print):
            # Optional local debug print; disabled by default to avoid terminal spam.
            print(
                f"[clock] game={payload['game_t']:.2f}s wall={payload['wall_t']:.2f}s "
                f"speed={payload['speed_x']:.3f}x "
                f"lag(p/s/t)=({payload['lag_production']:.3f}/{payload['lag_spending']:.3f}/{payload['lag_tech']:.3f}) "
                f"bank_pi={payload['bank_pi_output']:.3f}"
            )

    async def _safe_chat_send(self, bot, *, now: float, message: str) -> bool:
        if not bool(self.chat_enabled):
            return False
        if not str(message).strip():
            return False
        if (float(now) - float(self._chat_last_sent_t)) < float(self.chat_min_interval_s):
            return False
        try:
            await bot.chat_send(str(message))
            self._chat_last_sent_t = float(now)
            return True
        except Exception:
            return False

    def _enemy_inference_line(self, *, now: float) -> str:
        enemy_kind = str(self.awareness.mem.get(K("enemy", "opening", "kind"), now=now, default="NORMAL") or "NORMAL").upper()
        aggression_state = str(
            self.awareness.mem.get(K("enemy", "aggression", "state"), now=now, default="NONE") or "NONE"
        ).upper()
        snapshot = self.awareness.mem.get(K("enemy", "build", "snapshot"), now=now, default={}) or {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        top = snapshot.get("army_comp_top", [])
        top_unit = "unknown"
        top_count = 0
        if isinstance(top, list) and top:
            first = top[0] if isinstance(top[0], dict) else {}
            top_unit = str(first.get("unit", "unknown"))
            top_count = int(first.get("count", 0) or 0)
        bases_visible = int(snapshot.get("bases_visible", 0) or 0)

        if enemy_kind == "AGGRESSIVE" or aggression_state in {"RUSH", "AGGRESSION"}:
            return f"Intel: faca nos dentes ({top_unit} x{top_count}). Segura o tranco."
        if enemy_kind == "GREEDY":
            return f"Intel: greed detectado, eco aberto ({bases_visible} bases vistas). Hora de cobrar."
        return f"Intel: plano padrao estranho, sem caos por enquanto ({top_unit} x{top_count})."

    def _rush_held_summary_line(self, *, now: float) -> str:
        parity_state = str(
            self.awareness.mem.get(K("strategy", "parity", "state"), now=now, default="TRADEOFF_MIXED") or "TRADEOFF_MIXED"
        ).upper()
        parity_signals = self.awareness.mem.get(K("strategy", "parity", "signals"), now=now, default={}) or {}
        if not isinstance(parity_signals, dict):
            parity_signals = {}
        own_army = float(parity_signals.get("own_army_power", 0.0) or 0.0)
        enemy_army = float(parity_signals.get("enemy_army_power_est", 0.0) or 0.0)
        delta = float(own_army - enemy_army)

        if delta >= 6.0 or parity_state in {"AHEAD_BOTH", "AHEAD_ARMY_BEHIND_ECON"}:
            verdict = "foi bem"
        elif delta <= -6.0 or parity_state in {"BEHIND_BOTH", "BEHIND_ARMY_AHEAD_ECON"}:
            verdict = "foi mal"
        else:
            verdict = "foi ok"
        return (
            f"Rush segurado. Resultado: {verdict}. "
            f"Army power nosso/inimigo {own_army:.1f}/{enemy_army:.1f}, parity={parity_state}."
        )

    async def _emit_chat_updates(self, bot, *, now: float) -> None:
        # Build/opening selected
        opening_selected = str(self.awareness.mem.get(K("macro", "opening", "selected"), now=now, default="") or "")
        if not opening_selected:
            bor = getattr(bot, "build_order_runner", None)
            if bor is not None:
                opening_selected = str(getattr(bor, "chosen_opening", "") or "")
        if opening_selected and opening_selected != str(self._chat_last_opening):
            self._chat_last_opening = str(opening_selected)
            await self._safe_chat_send(bot, now=now, message=f"BO: {opening_selected}")

        transition_target = str(
            self.awareness.mem.get(K("macro", "opening", "transition_target"), now=now, default="") or ""
        ).upper()
        if transition_target and transition_target != str(self._chat_last_transition):
            self._chat_last_transition = str(transition_target)
            await self._safe_chat_send(bot, now=now, message=f"Transition: {transition_target}")

        # Enemy opening classifier
        enemy_kind = str(self.awareness.mem.get(K("enemy", "opening", "kind"), now=now, default="") or "").upper()
        aggression_state = str(
            self.awareness.mem.get(K("enemy", "aggression", "state"), now=now, default="NONE") or "NONE"
        ).upper()
        if (
            enemy_kind
            and (
                enemy_kind != str(self._chat_last_enemy_kind)
                or aggression_state != str(self._chat_last_aggression_state)
            )
        ):
            self._chat_last_enemy_kind = str(enemy_kind)
            self._chat_last_aggression_state = str(aggression_state)
            await self._safe_chat_send(bot, now=now, message=self._enemy_inference_line(now=now))

        # Rush state transitions
        prev_rush_state = str(self._chat_last_rush_state or "NONE").upper()
        rush_state = str(self.awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        rush_is_early = bool(float(now) <= float(self.opening_cfg.rush_phase_max_s))
        rush_active = rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}
        prev_rush_active = prev_rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}
        if rush_is_early and rush_active:
            self._chat_seen_early_rush = True
        if (
            self._chat_seen_early_rush
            and (not self._chat_rush_held_announced)
            and prev_rush_active
            and rush_state in {"ENDED", "NONE"}
        ):
            if await self._safe_chat_send(bot, now=now, message=self._rush_held_summary_line(now=now)):
                self._chat_rush_held_announced = True
        if rush_state and rush_state != str(self._chat_last_rush_state):
            self._chat_last_rush_state = str(rush_state)
            await self._safe_chat_send(bot, now=now, message=f"Rush: {rush_state}")


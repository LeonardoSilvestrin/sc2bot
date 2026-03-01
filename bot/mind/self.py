# bot/mind/self.py
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
import os
from pathlib import Path
import random
import time
import traceback
from typing import Any

from sc2.data import Result

from bot.devlog import DevLogger
from bot.sensors.threat_sensor import Threat
from bot.intel.enemy_build_intel import EnemyBuildIntelConfig, derive_enemy_build_intel
from bot.intel.game_parity_intel import GameParityIntelConfig, derive_game_parity_intel
from bot.intel.my_army_composition_intel import MyArmyCompositionConfig, derive_my_army_composition_intel
from bot.mind.attention import derive_attention
from bot.mind.awareness import Awareness, K
from bot.mind.body import UnitLeases
from bot.mind.ego import Ego, EgoConfig
from bot.tasks.base_task import TaskTick

from bot.tasks.defense.defend_task import Defend
from bot.tasks.macro.opening import MacroOpeningTick

from bot.planners.defense_planner import DefensePlanner
from bot.planners.intel_planner import IntelPlanner
from bot.planners.harass_planner import HarassPlanner
from bot.planners.reinforce_mission_planner import ReinforceMissionPlanner

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
    parity_cfg: GameParityIntelConfig
    my_comp_cfg: MyArmyCompositionConfig
    debug: bool = True
    attention_full_every_iters: int = 25
    awareness_full_every_iters: int = 50
    full_snapshots_default: bool = False
    full_snapshots_flag_path: str = "_prompt/full_snapshots.flag"
    bo_diag_every_iters: int = 25
    bo_stall_warn_s: float = 25.0
    state_snapshot_interval_s: float = 15.0
    awareness_snapshot_max_age_s: float | None = 180.0
    state_snapshots_default: bool = False
    default_opening: str = "Default"
    rush_opening: str = "DefensiveOpening"
    post_opening_transitions: tuple[str, ...] = ("STIM",)
    announce_opening_in_chat: bool = True
    announce_tactical_chat: bool = True
    announce_attack_chat: bool = True
    tactical_chat_min_interval_s: float = 22.0
    attack_chat_min_interval_s: float = 16.0
    _next_state_snapshot_t: float = 0.0
    _bo_last_step_idx: int = -1
    _bo_last_step_t: float = 0.0
    _last_tactical_chat_key: str = ""
    _last_tactical_chat_t: float = -9999.0
    _last_attack_chat_t: float = -9999.0
    _attack_alert_active: bool = False
    perf_snapshot_interval_s: float = 10.0
    enemy_build_every_iters: int = 4
    parity_every_iters: int = 4
    my_comp_every_iters: int = 4
    _next_perf_snapshot_t: float = 0.0
    clock_print_interval_s: float = 10.0
    _wall_start_real_s: float = 0.0
    _last_clock_print_t: float = -9999.0

    @classmethod
    def build(cls, *, log: DevLogger, debug: bool = True) -> "RuntimeApp":
        awareness = Awareness(log=None)
        threat = Threat(defend_radius=22.0, min_enemy=1)
        body = UnitLeases(default_ttl=8.0)

        ego = Ego(
            body=body,
            log=log,
            cfg=EgoConfig(
                singleton_domains=frozenset({"MACRO", "HARASS"}),
                threat_block_start_at=70,
                threat_force_preempt_at=90,
                non_preemptible_grace_s=2.5,
                default_failure_cooldown_s=8.0,
                macro_task_min_step_interval_s=0.35,
                perf_log_interval_s=3.5,
            ),
        )

        defend_task = Defend(log=log, log_every_iters=11)

        # Opening remains a tiny SCV-only macro while BuildRunner/YML does the rest.
        opening_macro_task = MacroOpeningTick(log=log, log_every_iters=22, scv_cap=60)

        defense_planner = DefensePlanner(defend_task=defend_task, log=log)
        intel_planner = IntelPlanner(awareness=awareness, log=log)
        harass_planner = HarassPlanner(log=log)
        reinforce_mission_planner = ReinforceMissionPlanner(log=log)

        macro_orchestrator_planner = MacroOrchestratorPlanner(log=log)
        # Planner cadence: avoid recomputing heavy macro/planning logic every frame.
        setattr(defense_planner, "propose_every_iters", 2)
        setattr(intel_planner, "propose_every_iters", 2)
        setattr(harass_planner, "propose_every_iters", 4)
        setattr(reinforce_mission_planner, "propose_every_iters", 4)
        setattr(macro_orchestrator_planner, "propose_every_iters", 10)

        # Keep opening as a pre-macro handled by its own lightweight planner.
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
                        domain="MACRO",
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
        setattr(opening_planner, "propose_every_iters", 2)

        ego.register_planners(
            [
                defense_planner,
                intel_planner,
                harass_planner,
                reinforce_mission_planner,
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
            parity_cfg=GameParityIntelConfig(),
            my_comp_cfg=MyArmyCompositionConfig(),
            debug=bool(debug),
        )

    async def on_start(self, bot) -> None:
        try:
            self.body.reset()
        except Exception:
            pass
        self._wall_start_real_s = float(time.perf_counter())
        self._last_clock_print_t = -9999.0
        self._sync_opening_done_contract(bot, now=float(getattr(bot, "time", 0.0) or 0.0))
        await self._select_and_announce_opening(bot)
        self._next_state_snapshot_t = 0.0
        self._emit_wall_dump(bot)
        if self.log:
            self.log.emit("runtime_start", {})

    async def _select_and_announce_opening(self, bot) -> None:
        bor = getattr(bot, "build_order_runner", None)
        if bor is None:
            return

        current = str(getattr(bor, "chosen_opening", "") or "")
        chosen = str(self.default_opening or "Default")
        switched = False
        try:
            if chosen != current:
                bor.switch_opening(chosen, remove_completed=False)
                switched = True
        except Exception:
            chosen = current or chosen

        now = float(getattr(bot, "time", 0.0) or 0.0)
        self.awareness.mem.set(K("macro", "opening", "selected"), value=str(chosen), now=now, ttl=None)
        self.awareness.mem.set(K("macro", "opening", "selection_mode"), value="default_opening", now=now, ttl=None)

        transition_pool = [str(x).strip().upper() for x in (self.post_opening_transitions or ()) if str(x).strip()]
        if not transition_pool:
            transition_pool = ["STIM"]
        transition_target = str(random.choice(transition_pool))
        self.awareness.mem.set(K("macro", "opening", "transition_target"), value=str(transition_target), now=now, ttl=None)
        self.awareness.mem.set(K("macro", "opening", "transition_set_at"), value=float(now), now=now, ttl=None)

        if self.log:
            self.log.emit(
                "opening_selected",
                {
                    "current": str(current),
                    "chosen": str(chosen),
                    "pool": [str(chosen)],
                    "switched": bool(switched),
                    "transition_target": str(transition_target),
                },
                meta={"module": "runtime", "component": "runtime.opening"},
            )

        if not bool(self.announce_opening_in_chat):
            return
        try:
            await bot.chat_send(f"Opening: {chosen} | Transition: {transition_target}")
        except Exception:
            # Ladder/engine can reject chat; log already contains selected opening.
            pass

    def _sync_opening_done_contract(self, bot, *, now: float) -> None:
        bor = getattr(bot, "build_order_runner", None)
        done = bool(getattr(bor, "build_completed", False)) if bor is not None else False
        self.awareness.mem.set(K("macro", "opening", "done"), value=bool(done), now=float(now), ttl=2.5)
        self.awareness.mem.set(K("macro", "opening", "done_owner"), value="runtime.build_order_runner", now=float(now), ttl=2.5)

    async def _maybe_switch_opening_for_rush(self, bot, *, now: float) -> None:
        bor = getattr(bot, "build_order_runner", None)
        if bor is None:
            return
        rush_state = str(self.awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        if rush_state not in {"SUSPECTED", "CONFIRMED", "HOLDING"}:
            return
        rush_conf = float(self.awareness.mem.get(K("enemy", "rush", "confidence"), now=now, default=0.0) or 0.0)
        last_pressure_t = float(self.awareness.mem.get(K("enemy", "rush", "last_seen_pressure_t"), now=now, default=0.0) or 0.0)
        pressure_clear_s = max(0.0, float(now) - float(last_pressure_t))
        recent_pressure = bool(pressure_clear_s <= 22.0)
        allow_confirmed = bool(rush_state == "CONFIRMED" and (recent_pressure or rush_conf >= 0.90))
        allow_suspected = bool(rush_state in {"SUSPECTED", "HOLDING"} and recent_pressure and rush_conf >= 0.78)
        if not (allow_confirmed or allow_suspected):
            return
        if bool(getattr(bor, "build_completed", False)):
            return
        current = str(getattr(bor, "chosen_opening", "") or "")
        target = str(self.rush_opening or "DefensiveOpening")
        if not target or current == target:
            return
        try:
            bor.switch_opening(target, remove_completed=False)
        except Exception:
            return
        self.awareness.mem.set(K("macro", "opening", "selected"), value=str(target), now=now, ttl=None)
        self.awareness.mem.set(K("macro", "opening", "selection_mode"), value="rush_override", now=now, ttl=None)
        self.awareness.mem.set(K("macro", "opening", "rush_override_at"), value=float(now), now=now, ttl=None)
        if self.log is not None:
            self.log.emit(
                "opening_switched_for_rush",
                {
                    "t": round(float(now), 2),
                    "from": str(current),
                    "to": str(target),
                    "rush_state": str(rush_state),
                    "rush_confidence": round(float(rush_conf), 3),
                    "recent_pressure": bool(recent_pressure),
                    "pressure_clear_s": round(float(pressure_clear_s), 2),
                },
                meta={"module": "runtime", "component": "runtime.opening"},
            )
        if bool(self.announce_opening_in_chat):
            try:
                await bot.chat_send("Rush detectado: trocando opening para defesa.")
            except Exception:
                pass

    async def on_step(self, bot, *, iteration: int) -> None:
        now = float(getattr(bot, "time", 0.0))
        try:
            t_total_0 = time.perf_counter()
            # Emit clock first so it still appears even if later stages throw.
            self._emit_runtime_clock(now=now)
            self._sync_opening_done_contract(bot, now=now)
            t0 = time.perf_counter()
            attention = derive_attention(bot, awareness=self.awareness, threat=self.threat, log=None)
            attention_ms = (time.perf_counter() - t0) * 1000.0

            enemy_build_ms = 0.0
            if int(iteration) % max(1, int(self.enemy_build_every_iters)) == 0:
                t0 = time.perf_counter()
                derive_enemy_build_intel(
                    bot,
                    awareness=self.awareness,
                    attention=attention,
                    now=now,
                    cfg=self.enemy_build_cfg,
                )
                enemy_build_ms = (time.perf_counter() - t0) * 1000.0
            await self._maybe_switch_opening_for_rush(bot, now=now)
            parity_ms = 0.0
            need_parity_bootstrap = self.awareness.mem.get(K("strategy", "parity", "overall"), now=now, default=None) is None
            if need_parity_bootstrap or (int(iteration) % max(1, int(self.parity_every_iters)) == 0):
                t0 = time.perf_counter()
                derive_game_parity_intel(
                    bot,
                    awareness=self.awareness,
                    attention=attention,
                    now=now,
                    cfg=self.parity_cfg,
                )
                parity_ms = (time.perf_counter() - t0) * 1000.0

            # New: strategy reference (mode + proportions)
            my_comp_ms = 0.0
            need_comp_bootstrap = self.awareness.mem.get(K("macro", "desired", "comp"), now=now, default=None) is None
            if need_comp_bootstrap or (int(iteration) % max(1, int(self.my_comp_every_iters)) == 0):
                t0 = time.perf_counter()
                derive_my_army_composition_intel(
                    awareness=self.awareness,
                    attention=attention,
                    now=now,
                    cfg=self.my_comp_cfg,
                )
                my_comp_ms = (time.perf_counter() - t0) * 1000.0

            await self._emit_reactive_chat(bot, attention=attention, now=now)

            self._emit_periodic_state_snapshots(now=now, attention=attention)

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
            t0 = time.perf_counter()
            await self.ego.tick(bot, tick=tick, attention=attention, awareness=self.awareness)
            ego_ms = (time.perf_counter() - t0) * 1000.0

            if self.log is not None and (self._next_perf_snapshot_t <= 0.0 or float(now) >= float(self._next_perf_snapshot_t)):
                total_ms = (time.perf_counter() - t_total_0) * 1000.0
                self.log.emit(
                    "perf_snapshot",
                    {
                        "iter": int(iteration),
                        "t": round(float(now), 2),
                        "on_step_total_ms": round(float(total_ms), 3),
                        "attention_ms": round(float(attention_ms), 3),
                        "enemy_build_ms": round(float(enemy_build_ms), 3),
                        "parity_ms": round(float(parity_ms), 3),
                        "my_comp_ms": round(float(my_comp_ms), 3),
                        "ego_ms": round(float(ego_ms), 3),
                        "awareness_facts": int(len(self.awareness.mem._facts)),
                        "ongoing_missions": int(len(attention.missions.ongoing)),
                    },
                    meta={"module": "runtime", "component": "runtime.perf"},
                )
                self._next_perf_snapshot_t = float(now) + max(2.0, float(self.perf_snapshot_interval_s))
        except Exception as e:
            if self.log is not None:
                self.log.emit(
                    "runtime_exception",
                    {
                        "iter": int(iteration),
                        "t": round(float(now), 2),
                        "error_type": type(e).__name__,
                        "error": str(e),
                        "traceback": traceback.format_exc(limit=20),
                    },
                    meta={"module": "runtime", "component": "runtime"},
                )
            # Keep bot alive to avoid hard-crash during ladder/local tests.
            return

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

    def _wall_dump_enabled(self) -> bool:
        if not bool(self.debug):
            return False
        raw = str(os.getenv("WALL_DUMP", "")).strip().lower()
        return raw in {"1", "true", "on", "yes"}

    @staticmethod
    def _spawn_label(bot) -> str:
        try:
            return "UpperSpawn" if float(bot.start_location.y) >= float(bot.game_info.map_center.y) else "LowerSpawn"
        except Exception:
            return "UnknownSpawn"

    @staticmethod
    def _dump_wall_slots_for_base(bot, *, base_location) -> list[list[float]]:
        try:
            from ares.consts import BuildingSize
        except Exception:
            return []
        try:
            placements = dict(bot.mediator.get_placements_dict or {})
        except Exception:
            return []
        if not placements:
            return []
        try:
            base_key = min(placements.keys(), key=lambda p: float(p.distance_to(base_location)))
        except Exception:
            return []
        if float(base_key.distance_to(base_location)) > 7.5:
            return []
        try:
            two_by_two = dict(placements[base_key][BuildingSize.TWO_BY_TWO] or {})
        except Exception:
            return []
        out: list[list[float]] = []
        for pos, info in two_by_two.items():
            if bool(info.get("is_wall", False)):
                out.append([round(float(pos.x), 1), round(float(pos.y), 1)])
        out.sort(key=lambda p: (p[0], p[1]))
        return out

    def _emit_wall_dump(self, bot) -> None:
        if not self._wall_dump_enabled():
            return

        map_name = str(getattr(getattr(bot, "game_info", None), "map_name", "") or "UnknownMap")
        spawn = self._spawn_label(bot)
        race_key = "VsAll"

        main_slots = self._dump_wall_slots_for_base(bot, base_location=bot.start_location)
        try:
            nat = bot.mediator.get_own_nat
        except Exception:
            nat = bot.start_location
        nat_slots = self._dump_wall_slots_for_base(bot, base_location=nat)

        yaml_hint = {
            map_name: {
                spawn: {
                    race_key: {
                        "SupplyDepotsWallMain": main_slots,
                        "SupplyDepotsWallNatural": nat_slots,
                    }
                }
            }
        }

        if self.log is not None:
            self.log.emit(
                "wall_placements_dump",
                {
                    "map": map_name,
                    "spawn": spawn,
                    "main_slots": main_slots,
                    "natural_slots": nat_slots,
                    "yaml_hint": yaml_hint,
                },
                meta={"module": "runtime", "component": "runtime.wall_dump"},
            )

        # Console hint for quick copy/paste during local testing.
        try:
            print("[WALL_DUMP]", yaml_hint)
        except Exception:
            pass

    def _state_snapshots_enabled(self) -> bool:
        if bool(self.state_snapshots_default):
            return True
        try:
            import os

            env = str(os.getenv("STATE_SNAPSHOTS", "")).strip().lower()
            return env in {"1", "true", "on", "yes"}
        except Exception:
            return False

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        try:
            import os

            raw = os.getenv(name, None)
            if raw is None or str(raw).strip() == "":
                return float(default)
            return float(raw)
        except Exception:
            return float(default)

    @staticmethod
    def _env_optional_float(name: str, default: float | None) -> float | None:
        try:
            import os

            raw = os.getenv(name, None)
            if raw is None or str(raw).strip() == "":
                return default
            s = str(raw).strip().lower()
            if s in {"none", "null", "off", "disable", "disabled", "0"}:
                return None
            return float(raw)
        except Exception:
            return default

    def _emit_periodic_state_snapshots(self, *, now: float, attention: Any) -> None:
        if self.log is None:
            return
        interval_s = max(
            1.0,
            float(
                self._env_float(
                    "STATE_SNAPSHOT_INTERVAL_S",
                    self.state_snapshot_interval_s,
                )
            ),
        )
        max_age_s = self._env_optional_float(
            "AWARENESS_SNAPSHOT_MAX_AGE_S",
            self.awareness_snapshot_max_age_s,
        )

        if float(now) + 1e-6 < float(self._next_state_snapshot_t):
            return

        rush_state = str(self.awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE")
        opening_kind = str(self.awareness.mem.get(K("enemy", "opening", "kind"), now=now, default="NORMAL") or "NORMAL")
        opening_conf = float(self.awareness.mem.get(K("enemy", "opening", "confidence"), now=now, default=0.0) or 0.0)
        parity_overall = str(self.awareness.mem.get(K("strategy", "parity", "overall"), now=now, default="EVEN") or "EVEN")
        lag_prod = float(self.awareness.mem.get(K("control", "priority", "lag", "production"), now=now, default=0.0) or 0.0)
        lag_spend = float(self.awareness.mem.get(K("control", "priority", "lag", "spending"), now=now, default=0.0) or 0.0)
        lag_tech = float(self.awareness.mem.get(K("control", "priority", "lag", "tech"), now=now, default=0.0) or 0.0)
        bank_pi = float(self.awareness.mem.get(K("control", "priority", "bank_pi_output"), now=now, default=0.0) or 0.0)
        reserve_spending_m = int(self.awareness.mem.get(K("macro", "reserve", "spending", "minerals"), now=now, default=0) or 0)
        reserve_spending_g = int(self.awareness.mem.get(K("macro", "reserve", "spending", "gas"), now=now, default=0) or 0)
        reserve_spending_block_prod = bool(
            self.awareness.mem.get(K("macro", "reserve", "spending", "block_production"), now=now, default=False)
        )
        reserve_tech_m = int(self.awareness.mem.get(K("macro", "reserve", "tech", "minerals"), now=now, default=0) or 0)
        reserve_tech_g = int(self.awareness.mem.get(K("macro", "reserve", "tech", "gas"), now=now, default=0) or 0)
        gas_status = dict(self.awareness.mem.get(K("macro", "gas", "status"), now=now, default={}) or {})

        try:
            ongoing = int(len(getattr(attention.missions, "ongoing", ()) or ()))
        except Exception:
            ongoing = 0

        self.log.emit(
            "state_snapshot",
            {
                "t": round(float(now), 2),
                "economy": {
                    "minerals": int(getattr(attention.economy, "minerals", 0) or 0),
                    "gas": int(getattr(attention.economy, "gas", 0) or 0),
                    "workers_total": int(getattr(attention.economy, "workers_total", 0) or 0),
                    "supply_used": int(getattr(attention.economy, "supply_used", 0) or 0),
                    "supply_left": int(getattr(attention.economy, "supply_left", 0) or 0),
                    "townhalls_total": int(getattr(attention.macro, "bases_total", 0) or 0),
                },
                "combat": {
                    "primary_urgency": int(getattr(attention.combat, "primary_urgency", 0) or 0),
                    "primary_enemy_count": int(getattr(attention.combat, "primary_enemy_count", 0) or 0),
                },
                "macro": {
                    "prod_structures_total": int(getattr(attention.macro, "prod_structures_total", 0) or 0),
                    "prod_structures_idle": int(getattr(attention.macro, "prod_structures_idle", 0) or 0),
                    "addon_reactor_ratio": round(float(getattr(attention.macro, "addon_reactor_ratio", 0.0) or 0.0), 3),
                    "addon_techlab_ratio": round(float(getattr(attention.macro, "addon_techlab_ratio", 0.0) or 0.0), 3),
                },
                "strategy": {
                    "rush_state": str(rush_state),
                    "enemy_opening_kind": str(opening_kind),
                    "enemy_opening_conf": round(float(opening_conf), 3),
                    "parity_overall": str(parity_overall),
                },
                "control": {
                    "lag_production": round(float(lag_prod), 3),
                    "lag_spending": round(float(lag_spend), 3),
                    "lag_tech": round(float(lag_tech), 3),
                    "bank_pi_output": round(float(bank_pi), 3),
                    "reserve_spending_m": int(reserve_spending_m),
                    "reserve_spending_g": int(reserve_spending_g),
                    "reserve_spending_block_production": bool(reserve_spending_block_prod),
                    "reserve_tech_m": int(reserve_tech_m),
                    "reserve_tech_g": int(reserve_tech_g),
                    "gas_mode": str(gas_status.get("mode", "")),
                    "gas_target_workers_per_refinery": int(gas_status.get("target_workers_per_refinery", 0) or 0),
                },
                "missions": {
                    "ongoing_count": int(ongoing),
                },
            },
            meta={"module": "runtime", "component": "runtime.state_snapshot"},
        )

        if not self._state_snapshots_enabled():
            self._next_state_snapshot_t = float(now) + float(interval_s)
            return

        self.log.emit(
            "attention_snapshot",
            {
                "t": round(float(now), 2),
                "snapshot": _jsonable(attention),
            },
            meta={"module": "attention", "component": "attention.snapshot"},
        )
        self.log.emit(
            "awareness_snapshot",
            {
                "t": round(float(now), 2),
                "mem": _jsonable(self.awareness.mem.snapshot(now=now, max_age=max_age_s)),
                "events_tail": _jsonable(self.awareness.tail_events(80)),
                "max_age_s": None if max_age_s is None else float(max_age_s),
            },
            meta={"module": "awareness", "component": "awareness.snapshot"},
        )

        self._next_state_snapshot_t = float(now) + float(interval_s)

    def _emit_runtime_clock(self, *, now: float) -> None:
        if (float(now) - float(self._last_clock_print_t)) < max(1.0, float(self.clock_print_interval_s)):
            return
        if self._wall_start_real_s <= 0.0:
            self._wall_start_real_s = float(time.perf_counter())
        real_elapsed = max(0.001, float(time.perf_counter()) - float(self._wall_start_real_s))
        game_elapsed = max(0.0, float(now))
        speed = float(game_elapsed / real_elapsed)
        lag_prod = float(self.awareness.mem.get(K("control", "priority", "lag", "production"), now=now, default=0.0) or 0.0)
        lag_spend = float(self.awareness.mem.get(K("control", "priority", "lag", "spending"), now=now, default=0.0) or 0.0)
        lag_tech = float(self.awareness.mem.get(K("control", "priority", "lag", "tech"), now=now, default=0.0) or 0.0)
        bank_pi = float(self.awareness.mem.get(K("control", "priority", "bank_pi_output"), now=now, default=0.0) or 0.0)
        print(
            (
                f"[clock] real={real_elapsed:.1f}s game={game_elapsed:.1f}s speed={speed:.2f}x "
                f"| pid p={lag_prod:.2f} s={lag_spend:.2f} t={lag_tech:.2f} bank={bank_pi:.2f}"
            ),
            flush=True,
        )
        if self.log is not None:
            self.log.emit(
                "runtime_clock",
                {
                    "t": round(float(now), 2),
                    "real_elapsed_s": round(float(real_elapsed), 2),
                    "game_elapsed_s": round(float(game_elapsed), 2),
                    "speed_x": round(float(speed), 3),
                    "lag_production": round(float(lag_prod), 3),
                    "lag_spending": round(float(lag_spend), 3),
                    "lag_tech": round(float(lag_tech), 3),
                    "bank_pi_output": round(float(bank_pi), 3),
                },
                meta={"module": "runtime", "component": "runtime.clock"},
            )
        self._last_clock_print_t = float(now)

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

        if step_idx != self._bo_last_step_idx:
            self._bo_last_step_idx = int(step_idx)
            self._bo_last_step_t = float(now)
        stall_s = max(0.0, float(now) - float(self._bo_last_step_t))

        command_name = ""
        start_at_supply = None
        target = None
        start_condition_ok = None
        end_condition_ok = None

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
                    "current_step_started": bool(current_step_started),
                    "current_step_complete": bool(current_step_complete),
                    "stall_s_on_step": round(float(stall_s), 2),
                },
                meta={"module": "macro", "component": "build_order.runner"},
            )

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        try:
            raw = os.getenv(name, None)
            if raw is None or str(raw).strip() == "":
                return bool(default)
            return str(raw).strip().lower() in {"1", "true", "on", "yes"}
        except Exception:
            return bool(default)

    @staticmethod
    def _is_attacking_now(attention) -> bool:
        for m in getattr(attention.missions, "ongoing", ()) or ():
            try:
                domain = str(getattr(m, "domain", "") or "").upper()
                pid = str(getattr(m, "proposal_id", "") or "").upper()
                status = str(getattr(m, "status", "") or "").upper()
            except Exception:
                continue
            if status != "RUNNING":
                continue
            if domain == "HARASS" or "HARASS" in pid:
                return True
        return False

    def _tactical_chat_signal(self, *, now: float) -> tuple[str, str] | None:
        rush_state = str(self.awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        opening_kind = str(self.awareness.mem.get(K("enemy", "opening", "kind"), now=now, default="NORMAL") or "NORMAL").upper()
        opening_conf = float(self.awareness.mem.get(K("enemy", "opening", "confidence"), now=now, default=0.0) or 0.0)

        if rush_state == "CONFIRMED":
            msg = random.choice(
                [
                    "Alerta: rush confirmado. Fechando a porta e segurando.",
                    "Rush detectado com força. Prioridade total na defesa.",
                    "Pressao inimiga confirmada. Jogando seguro agora.",
                ]
            )
            return "rush:confirmed", msg
        if rush_state in {"SUSPECTED", "HOLDING"}:
            msg = random.choice(
                [
                    "Sinal de rush. Mantendo defesa pronta.",
                    "Pode vir pressao cedo. Ajustando para segurar.",
                ]
            )
            return "rush:suspected", msg
        if rush_state == "ENDED":
            msg = random.choice(
                [
                    "A onda de rush passou. Voltando para macro.",
                    "Rush estabilizado. Reabrindo economia.",
                ]
            )
            return "rush:ended", msg
        if opening_kind == "GREEDY" and opening_conf >= 0.6:
            msg = random.choice(
                [
                    "Inimigo greedando. Hora de punir.",
                    "Leitura: adversario greed. Vamos acelerar o mapa.",
                ]
            )
            return "opening:greedy", msg
        if opening_kind == "NORMAL" and opening_conf >= 0.55:
            msg = random.choice(
                [
                    "Jogo estabilizado. Macro limpa e pressao controlada.",
                    "Leitura padrao no oponente. Seguimos plano solido.",
                ]
            )
            return "opening:normal", msg
        return None

    async def _emit_reactive_chat(self, bot, *, attention, now: float) -> None:
        if self._env_bool("ANNOUNCE_REACTIVE_CHAT", True):
            tactical_on = self._env_bool("ANNOUNCE_TACTICAL_CHAT", bool(self.announce_tactical_chat))
            attack_on = self._env_bool("ANNOUNCE_ATTACK_CHAT", bool(self.announce_attack_chat))
        else:
            tactical_on = False
            attack_on = False

        if tactical_on:
            signal = self._tactical_chat_signal(now=now)
            if signal is not None:
                key, msg = signal
                if key != str(self._last_tactical_chat_key) and (float(now) - float(self._last_tactical_chat_t)) >= float(
                    self.tactical_chat_min_interval_s
                ):
                    try:
                        await bot.chat_send(str(msg))
                        self._last_tactical_chat_key = str(key)
                        self._last_tactical_chat_t = float(now)
                    except Exception:
                        pass

        if attack_on:
            attacking_now = bool(self._is_attacking_now(attention))
            under_attack_now = bool(
                int(getattr(attention.combat, "primary_urgency", 0) or 0) >= 45
                or int(getattr(attention.combat, "primary_enemy_count", 0) or 0) >= 5
            )
            active = bool(attacking_now and under_attack_now)
            if active and not bool(self._attack_alert_active):
                if (float(now) - float(self._last_attack_chat_t)) >= float(self.attack_chat_min_interval_s):
                    msg = random.choice(
                        [
                            "Estamos atacando e tomando contra-pressao. Ajustando resposta.",
                            "Trade ativo: ofensiva fora e defesa em casa.",
                            "Ataque em andamento, mas base sob pressao. Rebalanceando agora.",
                        ]
                    )
                    try:
                        await bot.chat_send(str(msg))
                        self._last_attack_chat_t = float(now)
                    except Exception:
                        pass
            self._attack_alert_active = bool(active)


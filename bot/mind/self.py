# bot/mind/self.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ares.behaviors.macro.mining import Mining
from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.data import Result

from bot.devlog import DevLogger
from bot.intel.strategy.i2_CTRL_advantage_game_status_intel import AdvantageGameStatusIntel, AdvantageGameStatusIntelConfig
from bot.intel.locations.i1_pathing_flow_intel import PathingFlowIntelConfig, derive_pathing_flow_intel
from bot.intel.locations.i2_pathing_route_intel import PathingRouteIntelConfig, derive_pathing_route_intel
from bot.intel.locations.i3_map_control_intel import MapControlIntelConfig, derive_map_control_intel
from bot.intel.locations.i4_enemy_presence_intel import EnemyPresenceIntelConfig, derive_enemy_presence_intel
from bot.intel.locations.i5_frontline_intel import FrontlineIntelConfig, derive_frontline_intel
from bot.intel.locations.i6_territorial_control_intel import TerritorialControlConfig, derive_territorial_control_intel
from bot.intel.geometry.i1_world_compression_intel import WorldCompressionConfig, derive_world_compression
from bot.intel.geometry.i2_operational_geometry_intel import OperationalGeometryConfig, derive_operational_geometry
from bot.intel.strategy.i3_army_posture_intel import ArmyPostureIntelConfig, derive_army_posture_intel
from bot.intel.mission.i1_mission_unit_threat_intel import MissionUnitThreatIntelConfig, derive_mission_unit_threat_intel
from bot.intel.mission.i2_mission_value_intel import MissionValueIntelConfig, derive_mission_value_intel
from bot.sensors.threat_sensor import Threat
from bot.sensors.pathing_sensor import GroundAvoidanceSensorConfig, publish_ground_avoidance_sensor
from bot.intel.enemy.enemy_build_intel import EnemyBuildIntelConfig, derive_enemy_build_intel
from bot.intel.enemy.opening_contract import derive_opening_contract_intel
from bot.intel.strategy.i1_game_parity_intel import GameParityIntelConfig, derive_game_parity_intel
from bot.intel.macro.desired_intel import MyArmyCompositionConfig, derive_my_army_composition_intel
from bot.intel.enemy.opening_intel import OpeningIntelConfig, derive_enemy_opening_intel
from bot.mind.attention import derive_attention
from bot.mind.opening_state import apply_opening_request, require_active_opening_state, sync_opening_selection_from_runner
from bot.mind.awareness import Awareness, K
from bot.mind.body import UnitLeases
from bot.mind.ego import Ego, EgoConfig
from bot.tasks.base_task import TaskTick

from bot.tasks.defense.defend_task import Defend
from bot.tasks.defense.push_task import PushTask
from bot.tasks.macro.tasks.opening import MacroOpeningTick

from bot.planners.defense_planner import DefensePlanner
from bot.planners.harass_planner import HarassPlanner
from bot.planners.housekeeping_planner import HousekeepingPlanner
from bot.planners.intel_planner import IntelPlanner
from bot.planners.map_control_planner import MapControlPlanner
from bot.planners.reinforce_mission_planner import ReinforceMissionPlanner
from bot.planners.widowmine_planner import WidowminePlanner
from bot.planners.wall_planner import WallPlanner

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
    pathing_sensor_cfg: GroundAvoidanceSensorConfig
    pathing_flow_cfg: PathingFlowIntelConfig
    pathing_route_cfg: PathingRouteIntelConfig
    map_control_cfg: MapControlIntelConfig
    enemy_presence_cfg: EnemyPresenceIntelConfig
    frontline_cfg: FrontlineIntelConfig
    territorial_control_cfg: TerritorialControlConfig
    world_compression_cfg: WorldCompressionConfig
    operational_geometry_cfg: OperationalGeometryConfig
    army_posture_cfg: ArmyPostureIntelConfig
    mission_unit_threat_cfg: MissionUnitThreatIntelConfig
    mission_value_cfg: MissionValueIntelConfig
    advantage_game_status_intel: AdvantageGameStatusIntel
    debug: bool = True
    attention_full_every_iters: int = 25
    awareness_full_every_iters: int = 50
    full_snapshots_default: bool = False
    full_snapshots_flag_path: str = "_prompt/full_snapshots.flag"
    bo_diag_every_iters: int = 25
    bo_stall_warn_s: float = 25.0
    runtime_clock_every_iters: int = 24
    runtime_clock_print: bool = False
    scv_churn_window_s: float = 2.5
    scv_churn_emit_interval_s: float = 5.0
    scv_churn_min_changes: int = 4
    _bo_last_step_idx: int = -1
    _bo_last_step_t: float = 0.0
    _bo_last_opening: str = ""
    _chat_last_opening: str = ""
    _chat_last_transition: str = ""
    _chat_last_enemy_kind: str = ""
    _chat_last_rush_state: str = ""
    _chat_last_aggression_state: str = ""
    _chat_last_phase: str = ""
    _chat_last_status_sig: str = ""
    _chat_seen_early_rush: bool = False
    _chat_rush_held_announced: bool = False
    _chat_last_sent_t: float = -9999.0
    chat_enabled: bool = True
    chat_min_interval_s: float = 20.0
    chat_status_interval_s: float = 45.0
    _wall_start_s: float = 0.0
    _scv_state_by_tag: dict[int, dict[str, Any]] = field(default_factory=dict)
    _scv_churn_by_tag: dict[int, dict[str, Any]] = field(default_factory=dict)
    _lease_managed_scv_tags: set[int] = field(default_factory=set)

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
        reinforce_mission_planner = ReinforceMissionPlanner(log=log)
        widowmine_planner = WidowminePlanner(log=log)
        intel_planner = IntelPlanner(awareness=awareness, log=log)
        wall_planner = WallPlanner(log=log)
        housekeeping_planner = HousekeepingPlanner(log=log)
        macro_orchestrator_planner = MacroOrchestratorPlanner(log=log)
        map_control_planner = MapControlPlanner(log=log)

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

        @dataclass
        class PushPlanner:
            planner_id: str = "push_planner"

            def propose(self, bot, *, awareness: Awareness, attention) -> list:
                now = float(attention.time)

                timing_attacks = list(
                    awareness.mem.get(K("macro", "desired", "timing_attacks"), now=now, default=[]) or []
                )
                if not timing_attacks:
                    return []

                rush_state = str(
                    awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE"
                ).upper()
                if rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}:
                    return []

                try:
                    army_supply = float(getattr(bot, "supply_army", 0.0) or 0.0)
                except Exception:
                    army_supply = 0.0

                if int(attention.combat.primary_urgency) >= 40:
                    return []

                for attack in timing_attacks:
                    try:
                        hit_t = float(attack.get("hit_t", 9999.0))
                        prep_s = float(attack.get("prep_s", 60.0))
                        hold_s = float(attack.get("hold_s", 30.0))
                        army_supply_target = float(attack.get("army_supply_target", 40.0))
                    except Exception:
                        continue

                    window_start = hit_t - prep_s
                    window_end = hit_t + hold_s

                    if now < window_start or now > window_end:
                        continue
                    if army_supply < army_supply_target * 0.75:
                        continue

                    pid = f"push_planner:timing_push:{attack.get('name', 'unnamed')}"
                    if awareness.ops_proposal_running(proposal_id=pid, now=now):
                        return []

                    try:
                        target = bot.enemy_start_locations[0]
                    except Exception:
                        return []

                    end_t = window_end

                    _t, _e = target, end_t
                    def _factory(mission_id: str) -> PushTask:
                        return PushTask(target_pos=_t, end_t=_e)

                    return [Proposal(
                        proposal_id=pid,
                        domain="DEFENSE",
                        score=62,
                        tasks=[TaskSpec(
                            task_id="timing_push",
                            task_factory=_factory,
                            unit_requirements=[],
                            lease_ttl=float(hold_s) + 15.0,
                        )],
                        lease_ttl=float(hold_s) + 15.0,
                        cooldown_s=5.0,
                        risk_level=0,
                        allow_preempt=True,
                    )]

                return []

        push_planner = PushPlanner()

        ego.register_planners(
            [
                defense_planner,
                harass_planner,
                reinforce_mission_planner,
                widowmine_planner,
                intel_planner,
                map_control_planner,
                wall_planner,
                housekeeping_planner,
                opening_planner,
                push_planner,
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
            pathing_sensor_cfg=GroundAvoidanceSensorConfig(),
            pathing_flow_cfg=PathingFlowIntelConfig(),
            pathing_route_cfg=PathingRouteIntelConfig(),
            map_control_cfg=MapControlIntelConfig(),
            enemy_presence_cfg=EnemyPresenceIntelConfig(),
            frontline_cfg=FrontlineIntelConfig(),
            territorial_control_cfg=TerritorialControlConfig(),
            world_compression_cfg=WorldCompressionConfig(),
            operational_geometry_cfg=OperationalGeometryConfig(),
            army_posture_cfg=ArmyPostureIntelConfig(),
            mission_unit_threat_cfg=MissionUnitThreatIntelConfig(),
            mission_value_cfg=MissionValueIntelConfig(),
            advantage_game_status_intel=AdvantageGameStatusIntel(AdvantageGameStatusIntelConfig()),
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
        self._chat_last_phase = ""
        self._chat_last_status_sig = ""
        self._chat_seen_early_rush = False
        self._chat_rush_held_announced = False
        self._wall_start_s = float(time.perf_counter())
        self._scv_state_by_tag.clear()
        self._scv_churn_by_tag.clear()
        self._lease_managed_scv_tags.clear()
        derive_opening_contract_intel(
            bot,
            awareness=self.awareness,
            now=float(getattr(bot, "time", 0.0) or 0.0),
        )
        sync_opening_selection_from_runner(
            bot=bot,
            awareness=self.awareness,
            now=float(getattr(bot, "time", 0.0) or 0.0),
        )
        if self.log:
            self.log.emit("runtime_start", {})

    async def on_step(self, bot, *, iteration: int) -> None:
        now = float(getattr(bot, "time", 0.0))
        self._sync_leased_scv_roles(bot, now=now)
        # Keep Ares resource-manager bookkeeping actively applied each frame.
        bot.register_behavior(Mining())
        derive_opening_contract_intel(bot, awareness=self.awareness, now=now)
        sync_opening_selection_from_runner(bot=bot, awareness=self.awareness, now=now)
        publish_ground_avoidance_sensor(
            bot,
            awareness=self.awareness,
            now=now,
            cfg=self.pathing_sensor_cfg,
        )

        attention = derive_attention(bot, awareness=self.awareness, threat=self.threat, log=self.log)

        derive_enemy_opening_intel(
            bot,
            awareness=self.awareness,
            attention=attention,
            now=now,
            cfg=self.opening_cfg,
        )
        apply_opening_request(bot=bot, awareness=self.awareness, now=now, log=self.log)
        sync_opening_selection_from_runner(bot=bot, awareness=self.awareness, now=now)
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
        derive_pathing_flow_intel(
            bot,
            awareness=self.awareness,
            attention=attention,
            now=now,
            cfg=self.pathing_flow_cfg,
        )
        derive_pathing_route_intel(
            bot,
            awareness=self.awareness,
            attention=attention,
            now=now,
            cfg=self.pathing_route_cfg,
        )
        derive_enemy_presence_intel(
            bot,
            awareness=self.awareness,
            attention=attention,
            now=now,
            cfg=self.enemy_presence_cfg,
        )
        derive_map_control_intel(
            bot,
            awareness=self.awareness,
            attention=attention,
            now=now,
            cfg=self.map_control_cfg,
        )
        # Frontline intel: estado espacial das frentes (CLEAR/CONTESTED/COMPROMISED/LOST)
        # Deve rodar após map_control_intel (usa nat position) e enemy_presence_intel
        derive_frontline_intel(
            bot,
            awareness=self.awareness,
            now=now,
            cfg=self.frontline_cfg,
        )
        # WorldCompression: comprime percepções em vetor compacto de sinais
        # Deve rodar após frontline_intel, enemy_presence_intel, game_parity_intel
        derive_world_compression(
            bot,
            awareness=self.awareness,
            now=now,
            cfg=self.world_compression_cfg,
        )
        # OperationalGeometry: decide template e setores operacionais
        # Deve rodar após world_compression_intel
        derive_operational_geometry(
            bot,
            awareness=self.awareness,
            now=now,
            cfg=self.operational_geometry_cfg,
        )
        derive_territorial_control_intel(
            bot,
            awareness=self.awareness,
            now=now,
            cfg=self.territorial_control_cfg,
        )
        # Army posture intel: deriva postura operacional do bulk (anchor, detach_budget)
        # Agora lê do OperationalGeometry como fonte primária
        derive_army_posture_intel(
            bot,
            awareness=self.awareness,
            now=now,
            cfg=self.army_posture_cfg,
        )
        derive_mission_unit_threat_intel(
            bot,
            awareness=self.awareness,
            attention=attention,
            now=now,
            cfg=self.mission_unit_threat_cfg,
        )
        derive_mission_value_intel(
            bot,
            awareness=self.awareness,
            attention=attention,
            now=now,
            cfg=self.mission_value_cfg,
        )
        self.advantage_game_status_intel.step(
            attention=attention,
            awareness=self.awareness,
            now=now,
        )
        await self._emit_chat_updates(bot, now=now)

        self._emit_build_order_diagnostics(bot, now=now, iteration=int(iteration))
        self._emit_scv_churn_debug(bot, now=now)

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

    @staticmethod
    def _scv_roles_by_tag(bot) -> dict[int, UnitRole]:
        out: dict[int, UnitRole] = {}
        try:
            role_dict = getattr(bot.mediator, "get_unit_role_dict", {}) or {}
            for role, tags in dict(role_dict).items():
                for tag in list(tags or []):
                    try:
                        out[int(tag)] = role
                    except Exception:
                        continue
        except Exception:
            return {}
        return out

    def _desired_role_for_leased_scv(self, *, mission_id: str) -> UnitRole:
        commitment = getattr(self.ego, "_active", {}).get(str(mission_id))
        domain = str(getattr(commitment, "domain", "") or "").upper()
        if domain in {"INTEL", "SCOUT"}:
            return UnitRole.BUILD_RUNNER_SCOUT
        if domain in {"MAP_CONTROL", "DEFENSE"}:
            return UnitRole.REPAIRING
        return UnitRole.BUILDING

    def _sync_leased_scv_roles(self, bot, *, now: float) -> None:
        role_by_tag = self._scv_roles_by_tag(bot)
        try:
            building_tracker = dict(bot.mediator.get_building_tracker_dict or {})
        except Exception:
            building_tracker = {}

        leased_now: set[int] = set()
        for worker in list(getattr(bot, "workers", []) or []):
            try:
                if getattr(worker, "type_id", None) != U.SCV:
                    continue
                tag = int(getattr(worker, "tag", -1) or -1)
            except Exception:
                continue
            if tag <= 0:
                continue

            owner = self.body.owner_of(tag, now=now)
            if not owner:
                continue

            leased_now.add(tag)
            desired_role = self._desired_role_for_leased_scv(mission_id=str(owner))
            current_role = role_by_tag.get(tag)
            if current_role == desired_role:
                self._lease_managed_scv_tags.add(tag)
                continue
            try:
                bot.mediator.assign_role(tag=tag, role=desired_role, remove_from_squad=True)
                self._lease_managed_scv_tags.add(tag)
            except Exception:
                continue

        stale_tags = [int(tag) for tag in self._lease_managed_scv_tags if int(tag) not in leased_now]
        for tag in stale_tags:
            unit = bot.units.find_by_tag(int(tag))
            if unit is None or getattr(unit, "type_id", None) != U.SCV:
                self._lease_managed_scv_tags.discard(int(tag))
                continue
            if int(tag) in building_tracker or bool(getattr(unit, "is_constructing", False)):
                self._lease_managed_scv_tags.discard(int(tag))
                continue
            current_role = role_by_tag.get(int(tag))
            if current_role in {UnitRole.BUILDING, UnitRole.REPAIRING, UnitRole.BUILD_RUNNER_SCOUT}:
                try:
                    bot.mediator.assign_role(tag=int(tag), role=UnitRole.GATHERING, remove_from_squad=True)
                except Exception:
                    pass
            self._lease_managed_scv_tags.discard(int(tag))

    def _emit_scv_churn_debug(self, bot, *, now: float) -> None:
        if self.log is None:
            return

        role_by_tag: dict[int, str] = {}
        try:
            role_dict = getattr(bot.mediator, "get_unit_role_dict", {}) or {}
            for role, tags in dict(role_dict).items():
                role_name = str(getattr(role, "name", role) or "")
                for tag in list(tags or []):
                    try:
                        role_by_tag[int(tag)] = str(role_name)
                    except Exception:
                        continue
        except Exception:
            role_by_tag = {}

        alive_tags: set[int] = set()
        for worker in list(getattr(bot, "workers", []) or []):
            try:
                tag = int(getattr(worker, "tag", -1) or -1)
            except Exception:
                continue
            if tag <= 0:
                continue
            alive_tags.add(tag)

            orders = list(getattr(worker, "orders", []) or [])
            order_name = ""
            order_target = ""
            if orders:
                try:
                    order_name = str(getattr(getattr(orders[0], "ability", None), "name", "") or "")
                except Exception:
                    order_name = ""
                try:
                    target = getattr(worker, "order_target", None)
                    if hasattr(target, "x") and hasattr(target, "y"):
                        order_target = f"{float(getattr(target, 'x')):.1f},{float(getattr(target, 'y')):.1f}"
                    elif target is not None:
                        order_target = str(target)
                except Exception:
                    order_target = ""

            state = {
                "role": str(role_by_tag.get(tag, "UNKNOWN")),
                "order_name": str(order_name),
                "order_target": str(order_target),
                "is_idle": bool(getattr(worker, "is_idle", False)),
                "is_constructing": bool(getattr(worker, "is_constructing", False)),
            }
            prev = self._scv_state_by_tag.get(tag)
            self._scv_state_by_tag[tag] = dict(state)
            if prev is None or prev == state:
                continue

            churn = self._scv_churn_by_tag.get(
                tag,
                {"window_start": float(now), "changes": 0, "last_emit": -9999.0},
            )
            if (float(now) - float(churn.get("window_start", now) or now)) > float(self.scv_churn_window_s):
                churn["window_start"] = float(now)
                churn["changes"] = 0
            churn["changes"] = int(churn.get("changes", 0) or 0) + 1
            self._scv_churn_by_tag[tag] = churn

            if (
                int(churn["changes"]) >= int(self.scv_churn_min_changes)
                and (float(now) - float(churn.get("last_emit", -9999.0) or -9999.0)) >= float(self.scv_churn_emit_interval_s)
            ):
                churn["last_emit"] = float(now)
                self.log.emit(
                    "scv_order_churn",
                    {
                        "t": round(float(now), 2),
                        "tag": int(tag),
                        "changes_in_window": int(churn["changes"]),
                        "window_s": float(self.scv_churn_window_s),
                        "prev_role": str(prev.get("role", "")),
                        "role": str(state["role"]),
                        "prev_order": str(prev.get("order_name", "")),
                        "order": str(state["order_name"]),
                        "prev_target": str(prev.get("order_target", "")),
                        "target": str(state["order_target"]),
                        "is_idle": bool(state["is_idle"]),
                        "is_constructing": bool(state["is_constructing"]),
                    },
                    meta={"module": "runtime", "component": "runtime.scv_churn"},
                )

        stale_tags = [tag for tag in self._scv_state_by_tag.keys() if int(tag) not in alive_tags]
        for tag in stale_tags:
            self._scv_state_by_tag.pop(tag, None)
            self._scv_churn_by_tag.pop(tag, None)

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
        pathing_flow_conf = float(self.awareness.mem.get(K("enemy", "pathing", "flow", "confidence"), now=now, default=0.0) or 0.0)
        pathing_route = str(self.awareness.mem.get(K("enemy", "pathing", "route", "label"), now=now, default="") or "")
        pathing_pressure = int(self.awareness.mem.get(K("enemy", "pathing", "route", "pressure_on_us"), now=now, default=0) or 0)
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
            "pathing_flow_conf": round(float(pathing_flow_conf), 3),
            "pathing_route": str(pathing_route),
            "pathing_pressure_on_us": int(pathing_pressure),
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
        # Opening announcement (once).
        opening_selected, transition_target = require_active_opening_state(awareness=self.awareness, now=now)
        if opening_selected and opening_selected != str(self._chat_last_opening):
            self._chat_last_opening = str(opening_selected)
            msg = f"Opening: {opening_selected}"
            if transition_target:
                msg = f"{msg} -> {transition_target}"
            await self._safe_chat_send(bot, now=now, message=msg)
        self._chat_last_transition = str(transition_target)

        # Map controller intent: postura + info inimiga condensada.
        posture_snap = self.awareness.mem.get(K("strategy", "army", "snapshot"), now=now, default={}) or {}
        if not isinstance(posture_snap, dict):
            posture_snap = {}
        posture = str(posture_snap.get("posture", "HOLD_MAIN_RAMP") or "HOLD_MAIN_RAMP")
        army_supply = int(posture_snap.get("army_supply", 0) or 0)
        nat_ground = str(posture_snap.get("nat_ground_state", "CLEAR") or "CLEAR")
        rush_state = str(posture_snap.get("rush_state", "NONE") or "NONE").upper()

        enemy_kind = str(self.awareness.mem.get(K("enemy", "opening", "kind"), now=now, default="NORMAL") or "NORMAL").upper()
        build_snap = self.awareness.mem.get(K("enemy", "build", "snapshot"), now=now, default={}) or {}
        if not isinstance(build_snap, dict):
            build_snap = {}
        top = build_snap.get("army_comp_top", [])
        top_unit = "?"
        top_count = 0
        if isinstance(top, list) and top:
            first = top[0] if isinstance(top[0], dict) else {}
            top_unit = str(first.get("unit", "?"))
            top_count = int(first.get("count", 0) or 0)

        _POSTURE_LABEL = {
            "HOLD_MAIN_RAMP": "segurando rampa",
            "HOLD_NAT_CHOKE": "segurando choke nat",
            "SECURE_NAT": "tomando nat",
            "CONTROLLED_RETREAT": "recuando",
            "CONTROLLED_RETAKE": "retomando nat",
            "PRESS_FORWARD": "avancando",
            "ABANDON_EXPOSED_BASE": "abandonando base",
        }
        posture_label = _POSTURE_LABEL.get(posture, posture.lower())

        enemy_label = f"{top_unit}x{top_count}" if top_count > 0 else enemy_kind.lower()
        rush_suffix = f" [{rush_state}]" if rush_state not in {"NONE", ""} else ""

        msg = f"[{posture_label}] army={army_supply} nat={nat_ground.lower()} enemy={enemy_label}{rush_suffix}"
        sig = f"{posture}|{army_supply // 4}|{nat_ground}|{rush_state}|{top_unit}|{top_count // 2}"

        if sig != str(self._chat_last_status_sig):
            if await self._safe_chat_send(bot, now=now, message=msg):
                self._chat_last_status_sig = str(sig)

        self._chat_last_rush_state = str(rush_state)
        self._chat_last_aggression_state = ""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.utils.base_planner import BasePlanner
from bot.planners.utils.building_placement_planner import BuildingPlacementPlanner
from bot.planners.utils.proposals import Proposal, TaskSpec
from bot.planners.utils.spending_policy import SpendingPolicy
from bot.tasks.macro.tasks.macro_ares_executor_tick import MacroAresExecutorTick
from bot.tasks.tech.tasks.tech_ares_executor_tick import TechAresExecutorTick


@dataclass
class MacroOrchestratorPlanner(BasePlanner):
    planner_id: str = "macro_orchestrator_planner"
    score: int = 58
    planners: list[Any] = None
    log: DevLogger | None = None
    log_every_iters: int = 22

    army_executor_score: int = 60
    econ_executor_score: int = 58
    exec_min_interval_s: float = 1.2
    tech_executor_score: int = 44
    tech_exec_min_interval_s: float = 1.2
    tech_pause_prod_lag_threshold: float = 0.58
    tech_pause_army_lag_threshold: float = 0.40
    tech_pause_idle_structures_min: int = 3
    tech_priority_upgrade_release: tuple[str, ...] = ("STIMPACK",)
    critical_expand_cooldown_s: float = 12.0
    critical_gas_cooldown_s: float = 10.0
    lag_debug_emit_interval_s: float = 6.0

    phase_opening_max_s: float = 220.0
    phase_late_after_s: float = 620.0
    phase_late_bases: int = 4

    pressure_urgency_high: int = 18
    pressure_enemy_count_high: int = 3
    aggression_urgency_high: int = 14
    aggression_enemy_count_high: int = 2
    rush_phase_max_s: float = 180.0

    freeflow_on_minerals: int = 700
    freeflow_off_minerals: int = 450
    freeflow_hold_s: float = 8.0

    scv_cap_opening: int = 50
    scv_cap_mid: int = 66
    scv_cap_late: int = 78

    opening_gas_cap: int = 1
    late_gas_bonus: int = 1
    gas_target_workers_default: int = 3
    gas_target_workers_min: int = 0
    gas_overflow_hard: int = 650
    gas_overflow_soft: int = 420
    mineral_low_soft: int = 280
    gas_ratio_min_stock_hard: int = 280
    gas_ratio_min_stock_soft: int = 220
    gas_to_mineral_ratio_hard: float = 0.85
    gas_to_mineral_ratio_soft: float = 0.65
    gas_mode_hold_s: float = 16.0
    gas_workers_change_cooldown_s: float = 8.0
    gas_refineries_change_cooldown_s: float = 12.0
    bank_target_minerals: int = 650
    bank_target_gas: int = 220
    production_overflow_minerals: int = 350
    production_overflow_gas: int = 200
    production_overflow_off_minerals: int = 160
    production_overflow_off_gas: int = 80
    production_boost_utilization_min: float = 0.66
    production_boost_change_cooldown_s: float = 18.0
    production_boost_max: int = 2
    rush_production_overflow_minerals: int = 180
    rush_production_overflow_gas: int = 100
    rush_production_overflow_off_minerals: int = 80
    rush_production_overflow_off_gas: int = 40
    rush_production_boost_utilization_min: float = 0.38
    rush_production_boost_max: int = 3
    mineral_trend_alpha: float = 0.24
    mineral_trend_soft_per_s: float = 22.0
    mineral_trend_full_per_s: float = 140.0
    low_base_expand_boost: float = 0.34
    low_base_expand_prod_dampen: float = 0.22
    low_base_expand_spawn_dampen: float = 0.12
    lane_switch_margin: float = 0.12
    lane_min_hold_s: float = 6.0
    lane_watchdog_expand_minerals: int = 760
    lane_watchdog_expand_no_progress_s: float = 30.0
    emergency_dump_on_minerals: int = 1400
    emergency_dump_off_minerals: int = 1000
    emergency_dump_hold_s: float = 8.0
    ahead_expand_min_army_supply: float = 24.0
    rush_army_dump_minerals: int = 500
    aggression_army_dump_minerals: int = 900
    rush_natural_release_clear_s: float = 2.5
    rush_natural_release_min_army_supply: float = 4.0
    rush_natural_release_min_tanks: int = 0
    rush_natural_release_bunker_ok: bool = True
    rush_natural_release_requires_opening_done: bool = False
    rush_natural_prebank_clear_s: float = 1.25
    rush_natural_prebank_min_army_supply: float = 3.0
    rush_natural_prebank_minerals: int = 240
    enemy_macro_catchup_visible_bases: int = 3
    enemy_macro_catchup_base_gap: int = 2
    enemy_macro_catchup_clear_s: float = 4.0
    enemy_macro_catchup_min_army_supply: float = 10.0
    enemy_macro_catchup_min_tanks: int = 1
    enemy_macro_catchup_bunker_ok: bool = True
    enemy_at_door_urgency_floor: int = 16
    enemy_at_door_count_floor: int = 2
    natural_cc_force_minerals: int = 360

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
    _last_plan_hash: str = ""
    _plan_version: int = 0
    _resource_controller: SpendingPolicy = field(default_factory=SpendingPolicy)
    _placement_planner: BuildingPlacementPlanner = field(default_factory=BuildingPlacementPlanner)

    @staticmethod
    def _clamp01(x: float) -> float:
        return max(0.0, min(1.0, float(x)))

    def _enemy_at_door(self, bot, *, attention: Attention) -> bool:
        non_combat_units = {U.SCV, U.PROBE, U.DRONE, U.MULE, U.LARVA, U.EGG}
        non_threat_structures = {
            U.COMMANDCENTER,
            U.ORBITALCOMMAND,
            U.PLANETARYFORTRESS,
            U.HATCHERY,
            U.LAIR,
            U.HIVE,
            U.NEXUS,
        }

        def _hostile_count_near(pos, radius: float) -> int:
            total = 0
            for unit in list(getattr(bot, "enemy_units", []) or []):
                try:
                    if getattr(unit, "type_id", None) in non_combat_units:
                        continue
                    if float(unit.distance_to(pos)) <= float(radius):
                        total += 1
                except Exception:
                    continue
            for struct in list(getattr(bot, "enemy_structures", []) or []):
                try:
                    if getattr(struct, "type_id", None) in non_threat_structures:
                        continue
                    if float(struct.distance_to(pos)) <= float(radius):
                        total += 1
                except Exception:
                    continue
            return int(total)

        if (
            int(attention.combat.primary_urgency) >= int(self.enemy_at_door_urgency_floor)
            and int(attention.combat.primary_enemy_count) >= int(self.enemy_at_door_count_floor)
        ):
            return True
        try:
            ramp = getattr(bot, "main_base_ramp", None)
            if ramp is not None:
                probes = []
                top = getattr(ramp, "top_center", None)
                if top is not None:
                    probes.append((top, 5.5))
                for pos in list(getattr(ramp, "corner_depots", []) or []):
                    probes.append((pos, 4.5))
                barracks_pos = getattr(ramp, "barracks_correct_placement", None)
                if barracks_pos is not None:
                    probes.append((barracks_pos, 5.0))
                for pos, radius in probes:
                    if int(_hostile_count_near(pos, float(radius))) > 0:
                        return True
        except Exception:
            pass
        return False

    @staticmethod
    def _interp_scalar_milestones(*, milestones: list[dict[str, Any]], now: float, key: str) -> float:
        points: list[tuple[float, float]] = []
        for item in milestones:
            if not isinstance(item, dict):
                continue
            try:
                t = float(item.get("t", 0.0))
                v = float(item.get(key, 0.0))
            except Exception:
                continue
            points.append((t, max(0.0, v)))
        if not points:
            return 0.0
        points.sort(key=lambda x: x[0])
        t_now = float(now)
        if t_now <= points[0][0]:
            return float(points[0][1])
        for i in range(1, len(points)):
            t0, v0 = points[i - 1]
            t1, v1 = points[i]
            if t_now <= t1:
                alpha = max(0.0, min(1.0, (t_now - t0) / max(1e-6, t1 - t0)))
                return float(v0 + (alpha * (v1 - v0)))
        return float(points[-1][1])

    @staticmethod
    def _tech_due_targets_by_time(*, milestones: list[dict[str, Any]], now: float) -> tuple[dict[str, int], list[str]]:
        due_structures: dict[str, int] = {}
        due_upgrades: list[str] = []
        seen_upgrades: set[str] = set()
        for item in milestones:
            if not isinstance(item, dict):
                continue
            try:
                t = float(item.get("t", 0.0))
            except Exception:
                continue
            if float(t) > float(now):
                continue
            structures_raw = item.get("structures", {})
            if isinstance(structures_raw, dict):
                for name, target in structures_raw.items():
                    try:
                        tgt = max(0, int(target))
                    except Exception:
                        continue
                    n = str(name)
                    prev = int(due_structures.get(n, 0))
                    if tgt > prev:
                        due_structures[n] = int(tgt)
            upgrades_raw = item.get("upgrades", [])
            if isinstance(upgrades_raw, list):
                for name in upgrades_raw:
                    n = str(name)
                    if not n or n in seen_upgrades:
                        continue
                    seen_upgrades.add(n)
                    due_upgrades.append(n)
        return due_structures, due_upgrades

    def _publish_priority_lags(
        self,
        *,
        bot,
        awareness: Awareness,
        attention: Attention,
        now: float,
        desired_expand_to: int,
        scv_cap: int,
    ) -> tuple[float, float, float]:
        units_ready = dict(attention.economy.units_ready or {})
        minerals = int(attention.economy.minerals)
        gas = int(attention.economy.gas)
        bases_now = int(attention.macro.bases_total)
        workers_total = int(attention.economy.workers_total)

        trend_prev = awareness.mem.get(K("macro", "exec", "mineral_trend"), now=now, default={}) or {}
        if not isinstance(trend_prev, dict):
            trend_prev = {}
        prev_t = float(trend_prev.get("t", now) or now)
        prev_m = float(trend_prev.get("minerals", minerals) or minerals)
        prev_m_ema = float(trend_prev.get("ema_per_s", 0.0) or 0.0)
        dt_trend = max(1e-3, min(3.0, float(now) - float(prev_t)))
        mineral_net_per_s = (float(minerals) - float(prev_m)) / float(dt_trend)
        trend_alpha = self._clamp01(float(self.mineral_trend_alpha))
        mineral_trend_ema = ((1.0 - trend_alpha) * float(prev_m_ema)) + (trend_alpha * float(mineral_net_per_s))
        trend_soft = float(self.mineral_trend_soft_per_s)
        trend_span = max(1.0, float(self.mineral_trend_full_per_s) - float(trend_soft))
        mineral_trend_pressure = self._clamp01((float(mineral_trend_ema) - float(trend_soft)) / float(trend_span))
        low_base_factor = self._clamp01((3.0 - float(max(1, bases_now))) / 2.0)
        awareness.mem.set(
            K("macro", "exec", "mineral_trend"),
            value={
                "t": float(now),
                "minerals": int(minerals),
                "net_per_s": float(mineral_net_per_s),
                "ema_per_s": float(mineral_trend_ema),
                "pressure": float(mineral_trend_pressure),
                "low_base_factor": float(low_base_factor),
            },
            now=now,
            ttl=20.0,
        )

        # Production lag: unit-gap + idle pressure + army supply timing + structure-target deficit.
        signals = awareness.mem.get(K("macro", "desired", "signals"), now=now, default={}) or {}
        if not isinstance(signals, dict):
            signals = {}
        lagging_gap = float(signals.get("lagging_unit_gap", 0.0) or 0.0)
        prod_idle = int(attention.macro.prod_structures_idle)
        prod_total = int(attention.macro.prod_structures_total)
        idle_pressure = 0.0
        if prod_total > 0:
            idle_ratio = float(prod_idle) / float(max(1, prod_total))
            idle_pressure = self._clamp01(idle_ratio)
        army_milestones = awareness.mem.get(K("macro", "desired", "army_supply_milestones"), now=now, default=[]) or []
        if not isinstance(army_milestones, list):
            army_milestones = []
        expected_army_supply = self._interp_scalar_milestones(
            milestones=army_milestones,
            now=float(now),
            key="supply",
        )
        try:
            actual_army_supply = float(getattr(bot, "supply_army", 0.0) or 0.0)
        except Exception:
            actual_army_supply = 0.0
        army_supply_gap = max(0.0, float(expected_army_supply) - float(actual_army_supply))
        army_supply_pressure = self._clamp01(army_supply_gap / 18.0)
        desired_prod_structures_abs = awareness.mem.get(
            K("macro", "desired", "production_structure_targets"),
            now=now,
            default={},
        ) or {}
        if not isinstance(desired_prod_structures_abs, dict):
            desired_prod_structures_abs = {}
        desired_prod_scale = awareness.mem.get(
            K("macro", "control", "production_scale"),
            now=now,
            default={},
        ) or {}
        if not isinstance(desired_prod_scale, dict):
            desired_prod_scale = {}

        # Build baseline: max(absolute target from build, per-base scaled target).
        desired_prod_structures: dict[str, int] = {}
        for n in {"BARRACKS", "FACTORY", "STARPORT"}:
            abs_target = max(0, int(desired_prod_structures_abs.get(n, 0) or 0))
            scale = max(0.0, float(desired_prod_scale.get(n, 0.0) or 0.0))
            scaled_target = int((scale * float(max(1, bases_now))) + 0.999)
            desired_prod_structures[n] = max(abs_target, scaled_target)

        # Overflow boost (cooldown + hysteresis) to avoid barracks spam/chattering.
        bank_target_m = int(
            awareness.mem.get(
                K("macro", "control", "bank_target_minerals"),
                now=now,
                default=int(self.bank_target_minerals),
            )
            or int(self.bank_target_minerals)
        )
        bank_target_g = int(
            awareness.mem.get(
                K("macro", "control", "bank_target_gas"),
                now=now,
                default=int(self.bank_target_gas),
            )
            or int(self.bank_target_gas)
        )
        over_m = int(minerals) - int(bank_target_m)
        over_g = int(gas) - int(bank_target_g)
        mineral_overflow_pressure = self._clamp01(float(over_m) / float(max(160, bank_target_m)))
        low_base_expand_pressure = self._clamp01(
            (0.58 * float(mineral_overflow_pressure)) + (0.42 * float(mineral_trend_pressure))
        ) * float(low_base_factor)
        util = 1.0 - float(idle_pressure)
        expand_gap = max(0, int(desired_expand_to) - int(bases_now))
        workers_stable = bool(int(workers_total) >= max(1, int(scv_cap) - 1))
        rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        rush_tier = str(awareness.mem.get(K("enemy", "rush", "tier"), now=now, default="NONE") or "NONE").upper()
        rush_hard_active = bool(rush_state in {"CONFIRMED", "HOLDING"})
        rush_heavy_active = bool(rush_hard_active and rush_tier in {"HEAVY", "EXTREME"})
        rush_workers_stable = bool(int(workers_total) >= max(22, int(scv_cap) - 12))
        util_min = float(self.rush_production_boost_utilization_min) if rush_hard_active else float(self.production_boost_utilization_min)
        hold_boost_for_expand = bool(
            int(expand_gap) > 0
            and float(low_base_expand_pressure) >= 0.34
            and not bool(rush_heavy_active)
        )
        can_boost = bool(
            (rush_workers_stable if rush_hard_active else workers_stable)
            and (int(expand_gap) <= 0 or (rush_hard_active and not bool(hold_boost_for_expand)))
            and float(util) >= float(util_min)
        )
        over_m_on = int(self.rush_production_overflow_minerals) if rush_hard_active else int(self.production_overflow_minerals)
        over_g_on = int(self.rush_production_overflow_gas) if rush_hard_active else int(self.production_overflow_gas)
        over_m_off = int(self.rush_production_overflow_off_minerals) if rush_hard_active else int(self.production_overflow_off_minerals)
        over_g_off = int(self.rush_production_overflow_off_gas) if rush_hard_active else int(self.production_overflow_off_gas)
        boost_cap = int(self.rush_production_boost_max) if rush_hard_active else int(self.production_boost_max)
        construction_pressure = 0.0
        boost_target = 0
        if can_boost and (int(over_m) >= int(over_m_on) or int(over_g) >= int(over_g_on)):
            boost_target = 1
            if int(over_m) >= int(over_m_on) * 2:
                boost_target = 2
            if rush_heavy_active and (
                int(over_m) >= int(over_m_on) * 3
                or float(army_supply_pressure) >= 0.55
                or float(construction_pressure) >= 0.45
            ):
                boost_target = max(int(boost_target), 3)
        elif (int(over_m) <= int(over_m_off) and int(over_g) <= int(over_g_off)):
            boost_target = 0

        boost_target = max(0, min(int(boost_cap), int(boost_target)))
        boost_prev = int(awareness.mem.get(K("macro", "exec", "production_boost_level"), now=now, default=0) or 0)
        boost_changed_at = float(
            awareness.mem.get(K("macro", "exec", "production_boost_changed_at"), now=now, default=-9999.0) or -9999.0
        )
        boost_level = int(boost_prev)
        if int(boost_target) != int(boost_prev):
            if (float(now) - float(boost_changed_at)) >= float(self.production_boost_change_cooldown_s):
                boost_level = int(boost_target)
                awareness.mem.set(K("macro", "exec", "production_boost_changed_at"), value=float(now), now=now, ttl=30.0)
        awareness.mem.set(K("macro", "exec", "production_boost_level"), value=int(boost_level), now=now, ttl=30.0)

        # Choose primary structure for boost by current comp.
        desired_comp = awareness.mem.get(K("macro", "desired", "comp"), now=now, default={}) or {}
        if not isinstance(desired_comp, dict):
            desired_comp = {}
        air_w = sum(float(desired_comp.get(n, 0.0) or 0.0) for n in ("MEDIVAC", "VIKINGFIGHTER", "LIBERATOR", "BANSHEE", "RAVEN"))
        mech_w = sum(float(desired_comp.get(n, 0.0) or 0.0) for n in ("HELLION", "SIEGETANK", "CYCLONE", "THOR"))
        bio_w = sum(float(desired_comp.get(n, 0.0) or 0.0) for n in ("MARINE", "MARAUDER", "GHOST"))
        desired_signals = awareness.mem.get(K("macro", "desired", "signals"), now=now, default={}) or {}
        if not isinstance(desired_signals, dict):
            desired_signals = {}
        opening_selected = str(desired_signals.get("opening_selected", "") or "")
        if rush_hard_active or opening_selected == "RushDefenseOpen":
            boost_order = ["BARRACKS", "FACTORY", "STARPORT"]
        elif air_w >= mech_w and air_w >= bio_w:
            boost_order = ["STARPORT", "FACTORY", "BARRACKS"]
        elif mech_w >= bio_w:
            boost_order = ["FACTORY", "STARPORT", "BARRACKS"]
        else:
            boost_order = ["BARRACKS", "FACTORY", "STARPORT"]
        for i in range(int(boost_level)):
            desired_prod_structures[boost_order[i % len(boost_order)]] = int(desired_prod_structures.get(boost_order[i % len(boost_order)], 0)) + 1

        awareness.mem.set(
            K("macro", "exec", "production_structure_targets_dynamic"),
            value=dict(desired_prod_structures),
            now=now,
            ttl=15.0,
        )
        awareness.mem.set(
            K("macro", "exec", "production_structure_boost_status"),
            value={
                "level": int(boost_level),
                "target": int(boost_target),
                "can_boost": bool(can_boost),
                "over_m": int(over_m),
                "over_g": int(over_g),
                "utilization": float(util),
            },
            now=now,
            ttl=15.0,
        )
        prod_structure_missing = 0
        prod_structure_target_total = 0
        for name, target in desired_prod_structures.items():
            try:
                uid = getattr(U, str(name))
                tgt = max(0, int(target))
            except Exception:
                continue
            cur = int(units_ready.get(uid, 0) or 0)
            prod_structure_target_total += int(tgt)
            prod_structure_missing += max(0, int(tgt - cur))
        construction_pressure = self._clamp01(
            float(prod_structure_missing) / float(max(1, prod_structure_target_total))
        )
        lag_prod = self._clamp01(
            (0.44 * self._clamp01(lagging_gap / 24.0))
            + (0.14 * idle_pressure)
            + (0.24 * army_supply_pressure)
            + (0.18 * construction_pressure)
        )

        # Spending lag: unresolved expand targets should react to both stock and
        # sustained mineral accumulation, with extra pressure when we are still low-base.
        expand_gap = max(0, int(desired_expand_to) - int(bases_now))
        lag_spend = self._clamp01(
            (0.42 * self._clamp01(expand_gap / 2.0))
            + (0.22 * self._clamp01((minerals - 900.0) / 1300.0))
            + (0.18 * float(mineral_overflow_pressure))
            + (0.18 * float(low_base_expand_pressure))
        )

        # Tech lag: due-by-time upgrades/structures still missing (fallback to absolute targets).
        desired_tech = awareness.mem.get(K("macro", "desired", "tech_targets"), now=now, default={}) or {}
        if not isinstance(desired_tech, dict):
            desired_tech = {}
        desired_upgrades_all = (
            list(desired_tech.get("upgrades", []))
            if isinstance(desired_tech.get("upgrades", []), list)
            else []
        )
        desired_structures_all = (
            dict(desired_tech.get("structures", {}))
            if isinstance(desired_tech.get("structures", {}), dict)
            else {}
        )
        tech_milestones = awareness.mem.get(K("macro", "desired", "tech_timing_milestones"), now=now, default=[]) or []
        if not isinstance(tech_milestones, list):
            tech_milestones = []
        due_structures, due_upgrades = self._tech_due_targets_by_time(
            milestones=tech_milestones,
            now=float(now),
        )
        # Respect timing milestones: only due structures should influence immediate tech pressure.
        desired_structures = dict(due_structures)
        desired_upgrades = (
            [u for u in due_upgrades if u in set(str(x) for x in desired_upgrades_all)]
            if due_upgrades
            else list(desired_upgrades_all)
        )

        structure_missing = 0
        for name, target in desired_structures.items():
            try:
                uid = getattr(U, str(name))
                tgt = max(0, int(target))
            except Exception:
                continue
            cur = int(units_ready.get(uid, 0) or 0)
            structure_missing += max(0, int(tgt - cur))

        completed_upgrades = set(getattr(getattr(bot, "state", None), "upgrades", set()) or set())
        upgrade_missing = 0
        for name in desired_upgrades:
            try:
                from sc2.ids.upgrade_id import UpgradeId as Up  # local import to keep planner import surface small

                up = getattr(Up, str(name))
            except Exception:
                continue
            if up not in completed_upgrades:
                upgrade_missing += 1

        structure_target_total = sum(max(0, int(v)) for v in desired_structures.values())
        structure_missing_ratio = self._clamp01(float(structure_missing) / float(max(1, structure_target_total)))
        upgrade_missing_ratio = self._clamp01(float(upgrade_missing) / float(max(1, len(desired_upgrades))))
        lag_tech = self._clamp01((0.70 * structure_missing_ratio) + (0.30 * upgrade_missing_ratio))

        ttl = 12.0
        lag_debug = {
            "t": float(now),
            "lag_prod": float(lag_prod),
            "lag_spend": float(lag_spend),
            "lag_tech": float(lag_tech),
            "lagging_unit_gap": float(lagging_gap),
            "idle_pressure": float(idle_pressure),
            "army_supply_gap": float(army_supply_gap),
            "army_supply_pressure": float(army_supply_pressure),
            "construction_pressure": float(construction_pressure),
            "prod_structure_missing": int(prod_structure_missing),
            "prod_structure_target_total": int(prod_structure_target_total),
            "expand_gap": int(expand_gap),
            "desired_expand_to": int(desired_expand_to),
            "mineral_net_per_s": float(mineral_net_per_s),
            "mineral_trend_ema_per_s": float(mineral_trend_ema),
            "mineral_trend_pressure": float(mineral_trend_pressure),
            "mineral_overflow_pressure": float(mineral_overflow_pressure),
            "low_base_factor": float(low_base_factor),
            "low_base_expand_pressure": float(low_base_expand_pressure),
            "hold_boost_for_expand": bool(hold_boost_for_expand),
            "bases_now": int(bases_now),
            "minerals": int(minerals),
            "gas": int(gas),
            "structure_missing": int(structure_missing),
            "structure_target_total": int(structure_target_total),
            "structure_missing_ratio": float(structure_missing_ratio),
            "upgrade_missing": int(upgrade_missing),
            "upgrade_target_total": int(len(desired_upgrades)),
            "upgrade_missing_ratio": float(upgrade_missing_ratio),
            "workers_total": int(workers_total),
            "scv_cap": int(scv_cap),
        }
        awareness.mem.set(K("control", "priority", "lag", "debug"), value=dict(lag_debug), now=now, ttl=ttl)
        awareness.mem.set(K("control", "priority", "lag", "production"), value=float(lag_prod), now=now, ttl=ttl)
        awareness.mem.set(K("control", "priority", "lag", "construction"), value=float(construction_pressure), now=now, ttl=ttl)
        awareness.mem.set(K("control", "priority", "lag", "spending"), value=float(lag_spend), now=now, ttl=ttl)
        awareness.mem.set(K("control", "priority", "lag", "tech"), value=float(lag_tech), now=now, ttl=ttl)
        awareness.mem.set(K("control", "priority", "lag", "army_supply"), value=float(army_supply_pressure), now=now, ttl=ttl)
        awareness.mem.set(K("control", "priority", "lag", "mineral_trend"), value=float(mineral_trend_pressure), now=now, ttl=ttl)
        awareness.mem.set(K("control", "priority", "lag", "low_base_expand"), value=float(low_base_expand_pressure), now=now, ttl=ttl)
        if self.log is not None:
            last_emit = float(
                awareness.mem.get(K("control", "priority", "lag", "debug_last_emit_t"), now=now, default=0.0) or 0.0
            )
            lag_saturated = bool(float(lag_prod) >= 0.95 or float(lag_spend) >= 0.95 or float(lag_tech) >= 0.95)
            if lag_saturated and (float(now) - float(last_emit)) >= float(self.lag_debug_emit_interval_s):
                awareness.mem.set(K("control", "priority", "lag", "debug_last_emit_t"), value=float(now), now=now, ttl=30.0)
                self.log.emit(
                    "macro_lag_debug",
                    {
                        "t": round(float(now), 2),
                        "lag_prod": round(float(lag_prod), 3),
                        "lag_spend": round(float(lag_spend), 3),
                        "lag_tech": round(float(lag_tech), 3),
                        "lagging_unit_gap": round(float(lagging_gap), 2),
                        "army_supply_gap": round(float(army_supply_gap), 2),
                        "construction_pressure": round(float(construction_pressure), 3),
                        "expand_gap": int(expand_gap),
                        "minerals": int(minerals),
                        "gas": int(gas),
                        "structure_missing_ratio": round(float(structure_missing_ratio), 3),
                        "upgrade_missing_ratio": round(float(upgrade_missing_ratio), 3),
                        "prod_structure_missing": int(prod_structure_missing),
                        "prod_structure_target_total": int(prod_structure_target_total),
                    },
                    meta={"module": "planner", "component": f"planner.{self.planner_id}"},
                )
        return float(lag_prod), float(lag_spend), float(lag_tech)

    def _lane_order(
        self,
        *,
        awareness: Awareness,
        attention: Attention,
        now: float,
        pressure_high: bool,
        gas_target: int,
        workers_per_refinery: int,
        enable_workers: bool,
        enable_supply: bool,
        enable_gas: bool,
        enable_spawn: bool,
        enable_production: bool,
        enable_expansion: bool,
        scv_cap: int,
        expand_to: int,
        emergency_dump: bool,
        ahead_expand_push: bool,
        rush_army_dump: bool,
        enemy_macro_catchup: bool = False,
        rush_natural_release: bool = False,
    ) -> tuple[list[str], dict[str, float], str]:
        minerals = int(attention.economy.minerals)
        gas = int(attention.economy.gas)
        supply_left = int(attention.economy.supply_left)
        workers_total = int(attention.economy.workers_total)
        bases_now = int(attention.macro.bases_total)
        lag_prod = float(awareness.mem.get(K("control", "priority", "lag", "production"), now=now, default=0.0) or 0.0)
        lag_spend = float(awareness.mem.get(K("control", "priority", "lag", "spending"), now=now, default=0.0) or 0.0)
        lag_tech = float(awareness.mem.get(K("control", "priority", "lag", "tech"), now=now, default=0.0) or 0.0)
        lag_army = float(awareness.mem.get(K("control", "priority", "lag", "army_supply"), now=now, default=0.0) or 0.0)
        mineral_trend = float(awareness.mem.get(K("control", "priority", "lag", "mineral_trend"), now=now, default=0.0) or 0.0)
        low_base_expand = float(awareness.mem.get(K("control", "priority", "lag", "low_base_expand"), now=now, default=0.0) or 0.0)
        prod_idle = int(attention.macro.prod_structures_idle)
        prod_total = int(attention.macro.prod_structures_total)
        idle_ratio = self._clamp01(float(prod_idle) / float(max(1, prod_total)))

        # Expansion watchdog: if base count hasn't progressed for too long with high bank,
        # push expansion lane to the top.
        prev_bases = int(awareness.mem.get(K("macro", "exec", "obs", "bases"), now=now, default=bases_now) or bases_now)
        last_expand_progress_at = float(
            awareness.mem.get(K("macro", "exec", "obs", "expand_progress_at"), now=now, default=now) or now
        )
        if int(bases_now) > int(prev_bases):
            last_expand_progress_at = float(now)
        awareness.mem.set(K("macro", "exec", "obs", "bases"), value=int(bases_now), now=now, ttl=120.0)
        awareness.mem.set(
            K("macro", "exec", "obs", "expand_progress_at"),
            value=float(last_expand_progress_at),
            now=now,
            ttl=120.0,
        )
        no_expand_s = max(0.0, float(now) - float(last_expand_progress_at))

        expand_need = max(0, int(expand_to) - int(bases_now))
        worker_need = max(0, int(scv_cap) - int(workers_total))
        gas_pressure = self._clamp01((float(gas_target) / max(1.0, float(max(1, bases_now) * 2))) + (0.12 * float(lag_tech)))
        bank_m = self._clamp01((float(minerals) - 450.0) / 900.0)
        bank_g = self._clamp01((float(gas) - 140.0) / 600.0)

        scores: dict[str, float] = {}
        scores["workers"] = (0.20 + (0.55 * self._clamp01(worker_need / 18.0))) if enable_workers else -1.0
        if supply_left <= 2:
            scores["supply"] = 1.35 if enable_supply else -1.0
        elif supply_left <= 5:
            scores["supply"] = 0.70 if enable_supply else -1.0
        else:
            scores["supply"] = 0.08 if enable_supply else -1.0
        scores["gas"] = (0.12 + (0.55 * gas_pressure)) if enable_gas else -1.0
        scores["spawn"] = (
            (0.38 * float(lag_prod))
            + (0.26 * bank_m)
            + (0.12 * bank_g)
            + (0.34 * float(lag_army))
        ) if enable_spawn else -1.0
        scores["production"] = (
            (0.52 * float(lag_prod))
            + (0.36 * bank_m)
            + (0.12 * bank_g)
        ) if enable_production else -1.0
        if enable_spawn and prod_idle >= 2:
            scores["spawn"] += 0.24 + (0.36 * float(idle_ratio))
        if enable_production and prod_idle >= 2:
            scores["production"] -= 0.20 + (0.35 * float(idle_ratio))
        if float(lag_army) >= 0.35 and enable_spawn:
            scores["spawn"] += 0.10
        if float(lag_army) >= 0.45 and enable_production:
            scores["production"] -= 0.18
        scores["expand"] = (
            (0.50 * float(lag_spend))
            + (0.42 * bank_m)
            + (0.25 * self._clamp01(expand_need / 2.0))
        ) if enable_expansion else -1.0
        if enable_expansion:
            scores["expand"] += (float(self.low_base_expand_boost) * float(low_base_expand)) + (0.10 * float(mineral_trend))
        if enable_production:
            scores["production"] -= float(self.low_base_expand_prod_dampen) * float(low_base_expand)
        if enable_spawn:
            scores["spawn"] -= float(self.low_base_expand_spawn_dampen) * float(low_base_expand)

        if emergency_dump:
            scores["spawn"] += 0.42
            scores["production"] += 0.42
            scores["expand"] += 0.25

        if rush_army_dump:
            scores["spawn"] += 0.75
            scores["production"] += 0.12
            if not rush_natural_release:
                scores["expand"] -= max(0.18, 0.65 - (0.55 * float(low_base_expand)))
            scores["workers"] -= 0.20
        if rush_natural_release and enable_expansion:
            scores["expand"] += 0.60
            scores["spawn"] -= 0.20
        rush_tier = str(awareness.mem.get(K("enemy", "rush", "tier"), now=now, default="NONE") or "NONE").upper()
        if rush_tier in {"HEAVY", "EXTREME"}:
            scores["production"] += 0.26
            scores["expand"] -= 0.22
        if rush_tier == "EXTREME":
            scores["spawn"] += 0.18
            scores["workers"] -= 0.08

        if ahead_expand_push and enable_expansion:
            scores["expand"] += 0.48

        if pressure_high:
            scores["expand"] -= 0.35
            scores["spawn"] += 0.12
            scores["production"] += 0.05

        if enemy_macro_catchup and enable_expansion:
            scores["expand"] += 0.70
            scores["spawn"] -= 0.25

        if enable_expansion and expand_need > 0 and minerals >= int(self.lane_watchdog_expand_minerals):
            if no_expand_s >= float(self.lane_watchdog_expand_no_progress_s):
                scores["expand"] += 1.25

        lanes = [k for k, v in scores.items() if v >= 0.0]
        lanes_sorted = sorted(lanes, key=lambda ln: float(scores[ln]), reverse=True)
        if not lanes_sorted:
            return [], scores, ""

        prev_top = str(awareness.mem.get(K("macro", "exec", "lane_top"), now=now, default="") or "")
        hold_until = float(awareness.mem.get(K("macro", "exec", "lane_hold_until"), now=now, default=0.0) or 0.0)

        candidate_top = str(lanes_sorted[0])
        chosen_top = candidate_top
        if prev_top in lanes:
            if float(now) < float(hold_until):
                chosen_top = str(prev_top)
            else:
                prev_score = float(scores.get(prev_top, -1.0))
                cand_score = float(scores.get(candidate_top, -1.0))
                if prev_score >= (cand_score - float(self.lane_switch_margin)):
                    chosen_top = str(prev_top)

        if chosen_top != prev_top:
            awareness.mem.set(K("macro", "exec", "lane_hold_until"), value=float(now + self.lane_min_hold_s), now=now, ttl=30.0)
        awareness.mem.set(K("macro", "exec", "lane_top"), value=str(chosen_top), now=now, ttl=30.0)

        out_order = [chosen_top] + [ln for ln in lanes_sorted if ln != chosen_top]
        return out_order, scores, chosen_top

    def _phase(self, *, attention: Attention, now: float) -> str:
        if not bool(attention.macro.opening_done) and float(now) <= float(self.phase_opening_max_s):
            return "OPENING"
        if int(attention.macro.bases_total) >= int(self.phase_late_bases) or float(now) >= float(self.phase_late_after_s):
            return "LATE"
        return "MID"

    def _pressure_high(self, *, awareness: Awareness, attention: Attention, now: float) -> bool:
        rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        aggression_state = str(
            awareness.mem.get(K("enemy", "aggression", "state"), now=now, default="NONE") or "NONE"
        ).upper()
        rush_is_early = bool(float(now) <= float(self.rush_phase_max_s))
        return bool(
            int(attention.combat.primary_urgency) >= int(self.pressure_urgency_high)
            or int(attention.combat.primary_enemy_count) >= int(self.pressure_enemy_count_high)
            or (rush_is_early and rush_state in {"SUSPECTED", "CONFIRMED"})
            or (
                aggression_state in {"AGGRESSION", "RUSH"}
                and int(attention.combat.primary_urgency) >= int(self.aggression_urgency_high)
                and int(attention.combat.primary_enemy_count) >= int(self.aggression_enemy_count_high)
            )
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

    def _emergency_dump_hysteresis(self, *, awareness: Awareness, now: float, minerals: int, pressure_high: bool) -> bool:
        if pressure_high:
            awareness.mem.set(K("macro", "exec", "emergency_dump_state"), value=False, now=now, ttl=20.0)
            awareness.mem.set(K("macro", "exec", "emergency_dump_pending_since"), value=0.0, now=now, ttl=20.0)
            return False
        state = bool(awareness.mem.get(K("macro", "exec", "emergency_dump_state"), now=now, default=False))
        pending_since = float(
            awareness.mem.get(K("macro", "exec", "emergency_dump_pending_since"), now=now, default=0.0) or 0.0
        )
        if state:
            target_state = bool(int(minerals) >= int(self.emergency_dump_off_minerals))
        else:
            target_state = bool(int(minerals) >= int(self.emergency_dump_on_minerals))
        if target_state == state:
            awareness.mem.set(K("macro", "exec", "emergency_dump_pending_since"), value=0.0, now=now, ttl=20.0)
            return state
        if pending_since <= 0.0:
            awareness.mem.set(K("macro", "exec", "emergency_dump_pending_since"), value=float(now), now=now, ttl=20.0)
            return state
        if (float(now) - float(pending_since)) < float(self.emergency_dump_hold_s):
            return state
        awareness.mem.set(K("macro", "exec", "emergency_dump_state"), value=bool(target_state), now=now, ttl=20.0)
        awareness.mem.set(K("macro", "exec", "emergency_dump_pending_since"), value=0.0, now=now, ttl=20.0)
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

    def _publish_macro_plan_contract(self, *, awareness: Awareness, now: float, plan: dict[str, Any]) -> None:
        plan_json = json.dumps(plan, sort_keys=True, separators=(",", ":"))
        plan_hash = hashlib.sha1(plan_json.encode("utf-8")).hexdigest()[:12]
        if str(plan_hash) != str(self._last_plan_hash):
            self._plan_version = int(self._plan_version) + 1
            self._last_plan_hash = str(plan_hash)
            awareness.mem.set(K("macro", "plan", "changed_at"), value=float(now), now=now, ttl=None)
        awareness.mem.set(K("macro", "plan", "active"), value=dict(plan), now=now, ttl=15.0)
        awareness.mem.set(K("macro", "plan", "hash"), value=str(plan_hash), now=now, ttl=15.0)
        awareness.mem.set(K("macro", "plan", "version"), value=int(self._plan_version), now=now, ttl=None)
        awareness.mem.set(K("macro", "plan", "owner"), value=str(self.planner_id), now=now, ttl=15.0)

    def _publish_exec(self, bot, *, awareness: Awareness, attention: Attention, now: float) -> None:
        phase = self._phase(attention=attention, now=now)
        pressure_high = self._pressure_high(awareness=awareness, attention=attention, now=now)
        bases_now = int(attention.macro.bases_total)
        pending_cc = int(bot.already_pending(U.COMMANDCENTER) or 0)
        total_bases = int(bases_now + pending_cc)
        desired_signals = awareness.mem.get(K("macro", "desired", "signals"), now=now, default={}) or {}
        if not isinstance(desired_signals, dict):
            desired_signals = {}
        opening_selected = str(desired_signals.get("opening_selected", "") or "")
        enemy_build_snapshot = awareness.mem.get(K("enemy", "build", "snapshot"), now=now, default={}) or {}
        if not isinstance(enemy_build_snapshot, dict):
            enemy_build_snapshot = {}
        enemy_bases_visible = int(enemy_build_snapshot.get("bases_visible", 0) or 0)
        enemy_natural_on_ground = bool(enemy_build_snapshot.get("natural_on_ground", False))
        enemy_base_gap = max(0, int(enemy_bases_visible) - int(bases_now))
        rush_state_early = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        scout_no_natural_confirmed = bool(
            awareness.mem.get(K("enemy", "rush", "scout_no_natural_confirmed"), now=now, default=False)
        )
        enemy_one_base_rush = bool(
            rush_state_early in {"SUSPECTED", "CONFIRMED", "HOLDING"}
            and (bool(scout_no_natural_confirmed) or int(enemy_bases_visible) <= 1 or not bool(enemy_natural_on_ground))
        )

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

        parity_overall = str(awareness.mem.get(K("strategy", "parity", "overall"), now=now, default="EVEN") or "EVEN").upper()
        parity_econ = str(awareness.mem.get(K("strategy", "parity", "econ"), now=now, default="EVEN") or "EVEN").upper()
        parity_army = str(awareness.mem.get(K("strategy", "parity", "army"), now=now, default="EVEN") or "EVEN").upper()
        parity_state = str(
            awareness.mem.get(K("strategy", "parity", "state"), now=now, default="TRADEOFF_MIXED") or "TRADEOFF_MIXED"
        ).upper()
        parity_expand_bias = int(awareness.mem.get(K("strategy", "parity", "expand_bias"), now=now, default=0) or 0)
        parity_army_behind = float(
            awareness.mem.get(K("strategy", "parity", "severity", "army_behind"), now=now, default=0.0) or 0.0
        )
        try:
            army_supply = float(getattr(bot, "supply_army", 0.0) or 0.0)
        except Exception:
            army_supply = 0.0
        ahead_expand_push = bool(
            (not pressure_high)
            and phase != "OPENING"
            and army_supply >= float(self.ahead_expand_min_army_supply)
            and parity_expand_bias > 0
            and parity_overall == "AHEAD"
            and parity_econ != "BEHIND"
        )
        if ahead_expand_push:
            base_expand = max(int(base_expand), int(total_bases) + 1)
        if bool(enemy_one_base_rush) or str(opening_selected) == "RushDefenseOpen":
            base_expand = min(int(base_expand), 2)

        lag_prod, lag_spend, lag_tech = self._publish_priority_lags(
            bot=bot,
            awareness=awareness,
            attention=attention,
            now=now,
            desired_expand_to=max(1, int(base_expand)),
            scv_cap=int(scv_cap),
        )
        gas_decision = self._resource_controller.step(
            attention=attention,
            awareness=awareness,
            now=now,
            lag_tech=float(lag_tech),
            lag_spend=float(lag_spend),
            lag_prod=float(lag_prod),
            cfg=self,
        )
        gas_target = int(gas_decision.target_refineries)
        workers_per_refinery = int(gas_decision.target_workers_per_refinery)
        if phase == "OPENING":
            gas_target = min(int(gas_target), int(self.opening_gas_cap))
            workers_per_refinery = 3
        elif phase == "LATE" and not pressure_high:
            gas_target += int(self.late_gas_bonus)
        workers_per_refinery = max(0, min(3, int(workers_per_refinery)))

        freeflow_mode = self._freeflow_hysteresis(
            awareness=awareness,
            now=now,
            minerals=int(attention.economy.minerals),
            pressure_high=bool(pressure_high),
        )
        emergency_dump = self._emergency_dump_hysteresis(
            awareness=awareness,
            now=now,
            minerals=int(attention.economy.minerals),
            pressure_high=bool(pressure_high),
        )
        # If production is lagging and mineral bank is already high, prefer spend-first mode.
        if float(lag_prod) >= 0.70 and int(attention.economy.minerals) >= 600 and not bool(pressure_high):
            freeflow_mode = True
        if emergency_dump:
            freeflow_mode = True
        if phase == "OPENING":
            freeflow_mode = False

        rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        rush_tier = str(awareness.mem.get(K("enemy", "rush", "tier"), now=now, default="NONE") or "NONE").upper()
        rush_severity = float(awareness.mem.get(K("enemy", "rush", "severity"), now=now, default=0.0) or 0.0)
        rush_last_seen_pressure_t = float(
            awareness.mem.get(K("enemy", "rush", "last_seen_pressure_t"), now=now, default=0.0) or 0.0
        )
        aggression_state = str(
            awareness.mem.get(K("enemy", "aggression", "state"), now=now, default="NONE") or "NONE"
        ).upper()
        rush_is_early = bool(float(now) <= float(self.rush_phase_max_s))
        rush_active = bool(rush_is_early and rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"})
        rush_hard_active = bool(rush_state in {"CONFIRMED", "HOLDING"})
        rush_heavy_active = bool(rush_active and rush_tier in {"HEAVY", "EXTREME"})
        aggression_active = bool(aggression_state == "AGGRESSION")
        enemy_at_door = bool(self._enemy_at_door(bot, attention=attention))
        low_base_expand_pressure = float(
            awareness.mem.get(K("control", "priority", "lag", "low_base_expand"), now=now, default=0.0) or 0.0
        )
        lag_army = float(
            awareness.mem.get(K("control", "priority", "lag", "army_supply"), now=now, default=0.0) or 0.0
        )
        rush_army_dump = bool(
            rush_heavy_active
            or enemy_at_door
            or (
                rush_hard_active
                and float(low_base_expand_pressure) < 0.45
                and (
                    bool(pressure_high)
                    or float(lag_army) >= 0.36
                    or int(attention.combat.primary_enemy_count) >= 3
                    or float(rush_severity) >= 0.78
                    or int(attention.economy.minerals) >= int(self.rush_army_dump_minerals)
                )
            )
            or (rush_active and int(attention.economy.minerals) >= int(self.rush_army_dump_minerals))
            or (aggression_active and int(attention.economy.minerals) >= int(self.aggression_army_dump_minerals))
        )
        if rush_army_dump:
            freeflow_mode = True
        if rush_hard_active or rush_heavy_active:
            ahead_expand_push = False
        rush_clear_for = max(0.0, float(now) - float(rush_last_seen_pressure_t)) if float(rush_last_seen_pressure_t) > 0.0 else 9999.0
        try:
            tanks_ready = int(bot.units.of_type({U.SIEGETANK, U.SIEGETANKSIEGED}).ready.amount)
        except Exception:
            tanks_ready = 0
        try:
            bunkers_ready = int(bot.structures(U.BUNKER).ready.amount)
        except Exception:
            bunkers_ready = 0
        try:
            army_supply_now = float(getattr(bot, "supply_army", 0.0) or 0.0)
        except Exception:
            army_supply_now = 0.0
        nat_should_secure = bool(
            awareness.mem.get(K("intel", "map_control", "our_nat", "should_secure"), now=now, default=False)
        )
        nat_safe_to_land = bool(
            awareness.mem.get(K("intel", "map_control", "our_nat", "safe_to_land"), now=now, default=False)
        )
        our_bases = awareness.mem.get(K("intel", "our_bases", "registry"), now=now, default={}) or {}
        if not isinstance(our_bases, dict):
            our_bases = {}
        nat_base = dict(our_bases.get("NATURAL", {})) if isinstance(our_bases.get("NATURAL", {}), dict) else {}
        nat_owned = bool(nat_base.get("owned", False) or nat_base.get("townhall_tag"))
        nat_state = str(nat_base.get("state", "") or "").upper()
        nat_offsite = bool(nat_owned and nat_state in {"BUILDING_OFFSITE", "FLYING_TO_SITE", "LANDED_UNSAFE"})
        nat_is_mining = bool(nat_base.get("is_mining", False))
        nat_snapshot = awareness.mem.get(K("intel", "map_control", "our_nat", "snapshot"), now=now, default={}) or {}
        if not isinstance(nat_snapshot, dict):
            nat_snapshot = {}
        enemy_macro_lead_visible = bool(nat_snapshot.get("enemy_macro_lead_visible", False))
        delayed_natural_alarm = bool(nat_snapshot.get("delayed_natural_alarm", False))
        local_nat_cover_ready = bool(nat_snapshot.get("local_nat_cover_ready", False))
        natural_release_window = bool(nat_snapshot.get("natural_release_window", False))
        should_expand_offsite = bool(
            delayed_natural_alarm
            or enemy_macro_lead_visible
            or parity_overall == "BEHIND"
            or parity_army == "BEHIND"
            or parity_state in {"BEHIND_BOTH", "BEHIND_ARMY_AHEAD_ECON"}
            or parity_army_behind >= 0.32
        )
        enemy_macro_catchup_expand = bool(
            int(bases_now) < 2
            and int(enemy_bases_visible) >= int(self.enemy_macro_catchup_visible_bases)
            and int(enemy_base_gap) >= int(self.enemy_macro_catchup_base_gap)
            and not bool(pressure_high)
            and not bool(enemy_at_door)
            and not bool(rush_active)
            and float(rush_clear_for) >= float(self.enemy_macro_catchup_clear_s)
            and (
                bool(attention.macro.opening_done)
                or bool(enemy_natural_on_ground)
            )
            and (
                int(tanks_ready) >= int(self.enemy_macro_catchup_min_tanks)
                or float(army_supply_now) >= float(self.enemy_macro_catchup_min_army_supply)
                or (bool(self.enemy_macro_catchup_bunker_ok) and int(bunkers_ready) > 0)
                or bool(nat_should_secure)
            )
        )
        rush_natural_release = bool(
            int(bases_now) < 2
            and not bool(pressure_high)
            and (
                bool(attention.macro.opening_done)
                or not bool(self.rush_natural_release_requires_opening_done)
            )
            and not bool(rush_active)
            and not bool(enemy_at_door)
            and float(rush_clear_for) >= float(self.rush_natural_release_clear_s)
            and (
                bool(nat_safe_to_land)
                or bool(nat_should_secure)
                or (
                int(tanks_ready) >= int(self.rush_natural_release_min_tanks)
                or float(army_supply_now) >= float(self.rush_natural_release_min_army_supply)
                or (bool(self.rush_natural_release_bunker_ok) and int(bunkers_ready) > 0 and float(army_supply_now) >= 6.0)
                )
            )
        )
        natural_cc_force_now = bool(
            int(bases_now) < 2
            and int(pending_cc) <= 0
            and int(attention.economy.minerals) >= int(self.natural_cc_force_minerals)
            and not bool(enemy_at_door)
            and not bool(rush_active)
            and (
                bool(nat_safe_to_land)
                or bool(rush_natural_release)
                or bool(nat_should_secure)
                or bool(enemy_macro_catchup_expand)
            )
        )
        natural_prebank_now = bool(
            int(bases_now) < 2
            and int(pending_cc) <= 0
            and int(attention.economy.minerals) >= int(self.rush_natural_prebank_minerals)
            and not bool(nat_offsite)
            and not bool(enemy_at_door)
            and not bool(rush_active)
            and not bool(nat_is_mining)
            and (
                bool(natural_release_window)
                or (
                    bool(local_nat_cover_ready)
                    and float(rush_clear_for) >= float(self.rush_natural_prebank_clear_s)
                    and (
                        bool(nat_should_secure)
                        or bool(delayed_natural_alarm)
                        or float(army_supply_now) >= float(self.rush_natural_prebank_min_army_supply)
                        or int(bunkers_ready) > 0
                        or int(tanks_ready) > 0
                    )
                )
            )
        )

        expand_to = self._cooldown_value(
            awareness=awareness,
            now=now,
            key=K("macro", "exec", "expand_to"),
            changed_key=K("macro", "exec", "changed_at_expand_to"),
            proposed=max(1, int(base_expand)),
            cooldown_s=float(self.critical_expand_cooldown_s),
        )
        rush_defense_gate_active = bool(
            bool(enemy_one_base_rush)
            or (
                str(opening_selected) == "RushDefenseOpen"
                and (
                    rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}
                    or float(rush_clear_for) < float(self.rush_natural_release_clear_s)
                )
            )
        )
        if rush_defense_gate_active:
            expand_to = min(int(expand_to), 2)
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
        enable_production = True
        if enemy_at_door:
            enable_workers = bool(int(attention.economy.workers_total) < 24)
            enable_production = False
        if phase == "OPENING" and int(total_bases) < 2:
            enable_expansion = True
        if ahead_expand_push:
            enable_expansion = True
        if rush_army_dump or rush_hard_active:
            enable_expansion = False
            expand_to = min(int(expand_to), int(bases_now))
        if rush_defense_gate_active:
            if bool(rush_natural_release) or bool(enemy_macro_catchup_expand):
                enable_expansion = True
                expand_to = 2
                if bool(nat_safe_to_land):
                    enable_production = False
            else:
                enable_expansion = False
                expand_to = min(int(expand_to), min(2, int(bases_now)))
        if enemy_at_door:
            enable_expansion = False
            expand_to = min(int(expand_to), int(bases_now))
        if bool(enemy_macro_catchup_expand) and not bool(enemy_at_door):
            enable_expansion = True
            expand_to = max(2, int(expand_to))
        if natural_prebank_now:
            enable_expansion = True
            expand_to = max(2, int(expand_to))
            enable_production = False
        if natural_cc_force_now:
            enable_expansion = True
            expand_to = max(2, int(expand_to))
            enable_production = False

        natural_establish_critical = bool(
            int(bases_now) < 2
            and bool(nat_should_secure or delayed_natural_alarm or enemy_macro_lead_visible)
            and (bool(nat_offsite) or not bool(nat_owned) or not bool(nat_is_mining))
            and not bool(rush_defense_gate_active and not bool(rush_natural_release))
        )
        if natural_establish_critical:
            enable_expansion = True
            expand_to = max(2, int(expand_to))
            # Keep expansion urgent, but do not hard-disable production.
            # If the expand path stalls on placement/pathing, production must still scale.
            enable_production = bool(enable_production)

        if bool(nat_offsite) and not bool(rush_defense_gate_active and int(attention.combat.primary_enemy_count) > 0):
            enable_expansion = True
            expand_to = min(int(expand_to), 2)

        expand_target_label = ""
        expand_build_mode = "DIRECT"
        if int(expand_to) >= 2 and int(bases_now) < 2:
            # While NATURAL is unresolved, never request a third base target yet.
            # This prevents expansion lanes from reserving extra workers/CC intent.
            expand_to = min(int(expand_to), 2)
            expand_target_label = "NATURAL"
            expand_build_mode = "OFFSITE" if bool(should_expand_offsite) else "DIRECT"
            if bool(nat_offsite):
                enable_expansion = False
        elif int(expand_to) >= 3 and (bool(nat_offsite) or nat_state != "ESTABLISHED"):
            enable_expansion = False
            expand_to = min(int(expand_to), 2)
        offsite_natural_bootstrap = bool(
            int(bases_now) < 2
            and bool(should_expand_offsite)
            and not bool(nat_offsite)
            and not bool(nat_owned)
            and bool(attention.macro.opening_done)
            and (
                bool(enemy_at_door)
                or bool(rush_hard_active)
            )
            and bool(rush_natural_release)
        )
        if offsite_natural_bootstrap:
            expand_target_label = "NATURAL"
            expand_build_mode = "OFFSITE"
            enable_expansion = True
            expand_to = max(2, int(expand_to))

        lane_order, lane_scores, lane_top = self._lane_order(
            awareness=awareness,
            attention=attention,
            now=now,
            pressure_high=bool(pressure_high),
            gas_target=int(gas_target),
            workers_per_refinery=int(workers_per_refinery),
            enable_workers=bool(enable_workers),
            enable_supply=True,
            enable_gas=True,
            enable_spawn=True,
            enable_production=bool(enable_production),
            enable_expansion=bool(enable_expansion),
            scv_cap=int(scv_cap),
            expand_to=max(1, int(expand_to)),
            emergency_dump=bool(emergency_dump),
            ahead_expand_push=bool(ahead_expand_push),
            rush_army_dump=bool(rush_army_dump),
            enemy_macro_catchup=bool(enemy_macro_catchup_expand),
            rush_natural_release=bool(rush_natural_release),
        )
        if enemy_at_door:
            preferred = ["spawn", "supply", "workers", "gas"]
            lane_order = [ln for ln in preferred if ln in lane_order] + [ln for ln in lane_order if ln not in set(preferred)]

        ttl = 12.0
        awareness.mem.set(K("control", "phase"), value=str(phase), now=now, ttl=ttl)
        awareness.mem.set(K("control", "pressure", "level"), value=3 if pressure_high else 1, now=now, ttl=ttl)
        awareness.mem.set(K("control", "pressure", "threat_pos"), value=attention.combat.primary_threat_pos, now=now, ttl=ttl)

        awareness.mem.set(K("macro", "exec", "enable_workers"), value=bool(enable_workers), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "scv_cap"), value=int(scv_cap), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enable_supply"), value=True, now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enable_gas"), value=True, now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "gas_target"), value=int(gas_target), now=now, ttl=ttl)
        awareness.mem.set(
            K("macro", "gas", "target_workers_per_refinery"),
            value=int(workers_per_refinery),
            now=now,
            ttl=ttl,
        )
        awareness.mem.set(
            K("macro", "gas", "status"),
            value={
                "mode": str(gas_decision.mode),
                "target_refineries": int(gas_target),
                "target_workers_per_refinery": int(workers_per_refinery),
                "target_refineries_default": int(gas_decision.target_refineries_default),
                "gas_stock": int(gas_decision.gas_stock),
                "mineral_stock": int(gas_decision.mineral_stock),
                "gas_net_per_s": float(gas_decision.gas_net_per_s),
                "mineral_net_per_s": float(gas_decision.mineral_net_per_s),
                "gas_income_per_s": float(gas_decision.gas_income_per_s),
                "gas_spend_per_s": float(gas_decision.gas_spend_per_s),
                "mineral_income_per_s": float(gas_decision.mineral_income_per_s),
                "mineral_spend_per_s": float(gas_decision.mineral_spend_per_s),
                "gas_mix": float(gas_decision.gas_mix),
                "imbalance_slope": float(gas_decision.imbalance_slope),
                "changed_at": float(gas_decision.changed_at),
            },
            now=now,
            ttl=ttl,
        )
        awareness.mem.set(K("macro", "exec", "enable_spawn"), value=True, now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enable_orbital_morph"), value=True, now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "freeflow_mode"), value=bool(freeflow_mode), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "emergency_mineral_dump"), value=bool(emergency_dump), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "rush_army_dump"), value=bool(rush_army_dump), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "rush_heavy_active"), value=bool(rush_heavy_active), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "rush_tier"), value=str(rush_tier), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "rush_severity"), value=float(rush_severity), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enemy_bases_visible"), value=int(enemy_bases_visible), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enemy_base_gap"), value=int(enemy_base_gap), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enemy_macro_catchup_expand"), value=bool(enemy_macro_catchup_expand), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "ahead_expand_push"), value=bool(ahead_expand_push), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enable_production"), value=bool(enable_production), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enable_expansion"), value=bool(enable_expansion), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "expand_to"), value=int(expand_to), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "expand_target_label"), value=str(expand_target_label), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "expand_build_mode"), value=str(expand_build_mode), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "expand_safe_to_land"), value=bool(nat_safe_to_land), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "lane_order"), value=list(lane_order), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "lane_scores"), value=dict(lane_scores), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "lane_selected"), value=str(lane_top), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "cooldown_until"), value=0.0, now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "owner"), value=str(self.planner_id), now=now, ttl=ttl)
        self._publish_macro_plan_contract(
            awareness=awareness,
            now=now,
            plan={
                "phase": str(phase),
                "pressure_high": bool(pressure_high),
                "enable_workers": bool(enable_workers),
                "scv_cap": int(scv_cap),
                "enable_supply": True,
                "enable_gas": True,
                "gas_target": int(gas_target),
                "gas_workers_per_refinery": int(workers_per_refinery),
                "enable_spawn": True,
                "enable_orbital_morph": True,
                "freeflow_mode": bool(freeflow_mode),
                "emergency_mineral_dump": bool(emergency_dump),
                "rush_army_dump": bool(rush_army_dump),
                "rush_tier": str(rush_tier),
                "rush_severity": float(rush_severity),
                "rush_clear_for": float(rush_clear_for),
                "rush_natural_release": bool(rush_natural_release),
                "natural_prebank_now": bool(natural_prebank_now),
                "natural_cc_force_now": bool(natural_cc_force_now),
                "enemy_bases_visible": int(enemy_bases_visible),
                "enemy_base_gap": int(enemy_base_gap),
                "enemy_macro_catchup_expand": bool(enemy_macro_catchup_expand),
                "enemy_at_door": bool(enemy_at_door),
                "enable_production": bool(enable_production),
                "enable_expansion": bool(enable_expansion),
                "expand_to": int(expand_to),
                "expand_target_label": str(expand_target_label),
                "expand_build_mode": str(expand_build_mode),
                "expand_safe_to_land": bool(nat_safe_to_land),
                "ahead_expand_push": bool(ahead_expand_push),
                "lane_order": list(lane_order),
                "lane_scores": dict(lane_scores),
                "lane_selected": str(lane_top),
                "generated_at": float(now),
            },
        )

    def _publish_tech_exec(self, bot, *, awareness: Awareness, attention: Attention, now: float) -> None:
        bor = getattr(bot, "build_order_runner", None)
        opening_active = bool(bor is not None and not bool(getattr(bor, "build_completed", False)))
        desired_targets = awareness.mem.get(K("macro", "desired", "tech_targets"), now=now, default={}) or {}
        if not isinstance(desired_targets, dict):
            desired_targets = {}
        upgrades = list(desired_targets.get("upgrades", [])) if isinstance(desired_targets.get("upgrades", []), list) else []
        structures = dict(desired_targets.get("structures", {})) if isinstance(desired_targets.get("structures", {}), dict) else {}
        lag_prod = float(awareness.mem.get(K("control", "priority", "lag", "production"), now=now, default=0.0) or 0.0)
        lag_army = float(awareness.mem.get(K("control", "priority", "lag", "army_supply"), now=now, default=0.0) or 0.0)
        prod_idle = int(attention.macro.prod_structures_idle)
        pressure_high = self._pressure_high(awareness=awareness, attention=attention, now=now)
        emergency_dump = bool(awareness.mem.get(K("macro", "exec", "emergency_mineral_dump"), now=now, default=False))
        nat_should_secure = bool(
            awareness.mem.get(K("intel", "map_control", "our_nat", "should_secure"), now=now, default=False)
        )
        our_bases = awareness.mem.get(K("intel", "our_bases", "registry"), now=now, default={}) or {}
        if not isinstance(our_bases, dict):
            our_bases = {}
        nat_base = dict(our_bases.get("NATURAL", {})) if isinstance(our_bases.get("NATURAL", {}), dict) else {}
        nat_owned = bool(nat_base.get("owned", False) or nat_base.get("townhall_tag"))
        nat_is_mining = bool(nat_base.get("is_mining", False))
        rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        desired_signals = awareness.mem.get(K("macro", "desired", "signals"), now=now, default={}) or {}
        if not isinstance(desired_signals, dict):
            desired_signals = {}
        opening_selected = str(desired_signals.get("opening_selected", "") or "")
        rush_tech_locked = bool(
            opening_selected == "RushDefenseOpen"
            and rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}
        )
        tech_pause_for_army = bool(
            int(prod_idle) >= int(self.tech_pause_idle_structures_min)
            and (
                float(lag_prod) >= float(self.tech_pause_prod_lag_threshold)
                or float(lag_army) >= float(self.tech_pause_army_lag_threshold)
            )
        )
        tech_pause_for_expand = bool(
            int(attention.macro.bases_total) < 2
            and bool(nat_should_secure)
            and (not bool(nat_owned) or not bool(nat_is_mining))
        )
        completed_upgrades = set(getattr(getattr(bot, "state", None), "upgrades", set()) or set())
        priority_upgrade_pending = False
        priority_upgrade_names = {str(x).upper() for x in self.tech_priority_upgrade_release}
        for up_name in list(upgrades):
            name_u = str(up_name).upper()
            if name_u not in priority_upgrade_names:
                continue
            try:
                from sc2.ids.upgrade_id import UpgradeId as Up

                up_id = getattr(Up, name_u)
                if up_id not in completed_upgrades:
                    priority_upgrade_pending = True
                    break
            except Exception:
                continue
        if priority_upgrade_pending and int(attention.economy.minerals) >= 220:
            tech_pause_for_army = False
        enable = bool(
            (not opening_active)
            and (bool(upgrades) or bool(structures))
            and (not pressure_high)
            and (not emergency_dump)
            and (not rush_tech_locked)
            and (not tech_pause_for_army)
            and (not tech_pause_for_expand)
        )
        if pressure_high:
            reason = "paused_pressure_high"
        elif emergency_dump:
            reason = "paused_emergency_mineral_dump"
        elif rush_tech_locked:
            reason = "paused_rush_defense_active"
        elif tech_pause_for_army:
            reason = "paused_army_production_lag"
        elif tech_pause_for_expand:
            reason = "paused_until_natural_established"
        elif opening_active:
            reason = "paused_opening_active"
        elif not (bool(upgrades) or bool(structures)):
            reason = "paused_no_targets"
        else:
            reason = "enabled"

        ttl = 12.0
        awareness.mem.set(K("tech", "exec", "enable"), value=bool(enable), now=now, ttl=ttl)
        awareness.mem.set(
            K("tech", "exec", "targets"),
            value={"upgrades": list(upgrades), "structures": dict(structures)},
            now=now,
            ttl=ttl,
        )
        awareness.mem.set(
            K("tech", "exec", "status"),
            value={
                "enabled": bool(enable),
                "reason": str(reason),
                "lag_prod": float(lag_prod),
                "lag_army": float(lag_army),
                "prod_idle": int(prod_idle),
                "pressure_high": bool(pressure_high),
                "emergency_mineral_dump": bool(emergency_dump),
                "rush_tech_locked": bool(rush_tech_locked),
                "opening_selected": str(opening_selected),
            },
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
        self._placement_planner.publish(bot=bot, awareness=awareness, now=now)

        army_executor_pid = self.proposal_id("macro_army_executor")
        if not self.is_proposal_running(awareness=awareness, proposal_id=army_executor_pid, now=now):

            def _army_executor_factory(mission_id: str) -> MacroAresExecutorTick:
                return MacroAresExecutorTick(
                    awareness=awareness,
                    log=self.log,
                    log_every_iters=int(self.log_every_iters),
                    task_id="macro_army_executor",
                    domain="MACRO_ARMY_EXECUTOR",
                    commitment=10,
                    lane_whitelist=("workers", "supply", "gas", "spawn"),
                    force_front_lanes=("spawn", "supply"),
                )

            out.extend(
                self.make_single_task_proposal(
                    proposal_id=army_executor_pid,
                    domain="MACRO_ARMY_EXECUTOR",
                    score=int(self.army_executor_score),
                    task_spec=TaskSpec(
                        task_id="macro_army_executor",
                        task_factory=_army_executor_factory,
                        unit_requirements=[],
                    ),
                    lease_ttl=None,
                    cooldown_s=0.0,
                    risk_level=0,
                    allow_preempt=True,
                )
            )

        econ_executor_pid = self.proposal_id("macro_econ_executor")
        if not self.is_proposal_running(awareness=awareness, proposal_id=econ_executor_pid, now=now):

            def _econ_executor_factory(mission_id: str) -> MacroAresExecutorTick:
                return MacroAresExecutorTick(
                    awareness=awareness,
                    log=self.log,
                    log_every_iters=int(self.log_every_iters),
                    task_id="macro_econ_executor",
                    domain="MACRO_ECON_EXECUTOR",
                    commitment=10,
                    lane_whitelist=("expand", "production"),
                    force_front_lanes=("expand", "production"),
                )

            out.extend(
                self.make_single_task_proposal(
                    proposal_id=econ_executor_pid,
                    domain="MACRO_ECON_EXECUTOR",
                    score=int(self.econ_executor_score),
                    task_spec=TaskSpec(
                        task_id="macro_econ_executor",
                        task_factory=_econ_executor_factory,
                        unit_requirements=[],
                    ),
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

        return out

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        domain_proposals = self._make_domain_proposals(bot, awareness=awareness, attention=attention)
        if domain_proposals:
            now = float(attention.time)
            lane_order = awareness.mem.get(K("macro", "exec", "lane_order"), now=now, default=[]) or []
            lane_selected = awareness.mem.get(K("macro", "exec", "lane_selected"), now=now, default="") or ""
            lane_scores = awareness.mem.get(K("macro", "exec", "lane_scores"), now=now, default={}) or {}
            proposal_order = [
                {
                    "proposal_id": str(p.proposal_id),
                    "domain": str(p.domain),
                    "score": int(p.score),
                }
                for p in domain_proposals
            ]
            self.emit_planner_proposed(
                {
                    "count": len(domain_proposals),
                    "children": int(len(self.planners or [])),
                    "proposal_order": proposal_order,
                    "lane_selected": str(lane_selected),
                    "lane_order": list(lane_order) if isinstance(lane_order, list) else [],
                    "lane_scores": dict(lane_scores) if isinstance(lane_scores, dict) else {},
                }
            )
        return domain_proposals

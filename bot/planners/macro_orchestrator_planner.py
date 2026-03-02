from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.control import MacroResourceController
from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.utils.base_planner import BasePlanner
from bot.planners.utils.proposals import Proposal, TaskSpec
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

    phase_opening_max_s: float = 220.0
    phase_late_after_s: float = 620.0
    phase_late_bases: int = 4

    pressure_urgency_high: int = 18
    pressure_enemy_count_high: int = 3

    freeflow_on_minerals: int = 700
    freeflow_off_minerals: int = 450
    freeflow_hold_s: float = 8.0

    scv_cap_opening: int = 50
    scv_cap_mid: int = 66
    scv_cap_late: int = 78

    opening_gas_cap: int = 1
    late_gas_bonus: int = 1
    gas_target_workers_default: int = 2
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
    lane_switch_margin: float = 0.12
    lane_min_hold_s: float = 6.0
    lane_watchdog_expand_minerals: int = 900
    lane_watchdog_expand_no_progress_s: float = 42.0
    emergency_dump_on_minerals: int = 1400
    emergency_dump_off_minerals: int = 1000
    emergency_dump_hold_s: float = 8.0
    ahead_expand_min_army_supply: float = 24.0
    rush_army_dump_minerals: int = 500

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
    _resource_controller: MacroResourceController = field(default_factory=MacroResourceController)

    @staticmethod
    def _clamp01(x: float) -> float:
        return max(0.0, min(1.0, float(x)))

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
            K("macro", "desired", "production_scale"),
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
                K("macro", "desired", "bank_target_minerals"),
                now=now,
                default=int(self.bank_target_minerals),
            )
            or int(self.bank_target_minerals)
        )
        bank_target_g = int(
            awareness.mem.get(
                K("macro", "desired", "bank_target_gas"),
                now=now,
                default=int(self.bank_target_gas),
            )
            or int(self.bank_target_gas)
        )
        over_m = int(minerals) - int(bank_target_m)
        over_g = int(gas) - int(bank_target_g)
        util = 1.0 - float(idle_pressure)
        expand_gap = max(0, int(desired_expand_to) - int(bases_now))
        workers_stable = bool(int(workers_total) >= max(1, int(scv_cap) - 1))
        can_boost = bool(
            workers_stable
            and int(expand_gap) <= 0
            and float(util) >= float(self.production_boost_utilization_min)
        )
        boost_target = 0
        if can_boost and (int(over_m) >= int(self.production_overflow_minerals) or int(over_g) >= int(self.production_overflow_gas)):
            boost_target = 1
            if int(over_m) >= int(self.production_overflow_minerals) * 2:
                boost_target = 2
        elif (int(over_m) <= int(self.production_overflow_off_minerals) and int(over_g) <= int(self.production_overflow_off_gas)):
            boost_target = 0

        boost_target = max(0, min(int(self.production_boost_max), int(boost_target)))
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
        if air_w >= mech_w and air_w >= bio_w:
            boost_order = ["STARPORT", "FACTORY", "BARRACKS"]
        elif mech_w >= bio_w:
            boost_order = ["FACTORY", "STARPORT", "BARRACKS"]
        else:
            boost_order = ["BARRACKS", "FACTORY", "STARPORT"]
        for i in range(int(boost_level)):
            desired_prod_structures[boost_order[i % len(boost_order)]] = int(desired_prod_structures.get(boost_order[i % len(boost_order)], 0)) + 1

        awareness.mem.set(
            K("macro", "desired", "production_structure_targets_dynamic"),
            value=dict(desired_prod_structures),
            now=now,
            ttl=15.0,
        )
        awareness.mem.set(
            K("macro", "desired", "production_structure_boost_status"),
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

        # Spending lag: bank high while still below desired base count.
        expand_gap = max(0, int(desired_expand_to) - int(bases_now))
        lag_spend = self._clamp01((0.62 * self._clamp01(expand_gap / 2.0)) + (0.38 * self._clamp01((minerals - 900.0) / 1300.0)))

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
        desired_structures = dict(due_structures) if due_structures else dict(desired_structures_all)
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
        awareness.mem.set(K("control", "priority", "lag", "production"), value=float(lag_prod), now=now, ttl=ttl)
        awareness.mem.set(K("control", "priority", "lag", "construction"), value=float(construction_pressure), now=now, ttl=ttl)
        awareness.mem.set(K("control", "priority", "lag", "spending"), value=float(lag_spend), now=now, ttl=ttl)
        awareness.mem.set(K("control", "priority", "lag", "tech"), value=float(lag_tech), now=now, ttl=ttl)
        awareness.mem.set(K("control", "priority", "lag", "army_supply"), value=float(army_supply_pressure), now=now, ttl=ttl)
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
            (0.46 * float(lag_spend))
            + (0.34 * bank_m)
            + (0.20 * self._clamp01(expand_need / 2.0))
        ) if enable_expansion else -1.0

        if emergency_dump:
            scores["spawn"] += 0.42
            scores["production"] += 0.42
            scores["expand"] += 0.25

        if rush_army_dump:
            scores["spawn"] += 0.75
            scores["production"] += 0.12
            scores["expand"] -= 0.65
            scores["workers"] -= 0.20

        if ahead_expand_push and enable_expansion:
            scores["expand"] += 0.48

        if pressure_high:
            scores["expand"] -= 0.45
            scores["spawn"] += 0.12
            scores["production"] += 0.05

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
        parity_expand_bias = int(awareness.mem.get(K("strategy", "parity", "expand_bias"), now=now, default=0) or 0)
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
        rush_army_dump = bool(
            rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}
            and int(attention.economy.minerals) >= int(self.rush_army_dump_minerals)
        )
        if rush_army_dump:
            freeflow_mode = True

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
        if ahead_expand_push:
            enable_expansion = True
        if rush_army_dump:
            enable_expansion = False
            expand_to = min(int(expand_to), int(bases_now))

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
            enable_production=True,
            enable_expansion=bool(enable_expansion),
            scv_cap=int(scv_cap),
            expand_to=max(1, int(expand_to)),
            emergency_dump=bool(emergency_dump),
            ahead_expand_push=bool(ahead_expand_push),
            rush_army_dump=bool(rush_army_dump),
        )

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
        awareness.mem.set(K("macro", "exec", "ahead_expand_push"), value=bool(ahead_expand_push), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enable_production"), value=True, now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "enable_expansion"), value=bool(enable_expansion), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "exec", "expand_to"), value=int(expand_to), now=now, ttl=ttl)
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
                "enable_production": True,
                "enable_expansion": bool(enable_expansion),
                "expand_to": int(expand_to),
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
        tech_pause_for_army = bool(
            int(prod_idle) >= int(self.tech_pause_idle_structures_min)
            and (
                float(lag_prod) >= float(self.tech_pause_prod_lag_threshold)
                or float(lag_army) >= float(self.tech_pause_army_lag_threshold)
            )
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
            and (not tech_pause_for_army)
        )
        if pressure_high:
            reason = "paused_pressure_high"
        elif emergency_dump:
            reason = "paused_emergency_mineral_dump"
        elif tech_pause_for_army:
            reason = "paused_army_production_lag"
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

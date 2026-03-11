from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict

from ares.dicts.cost_dict import COST_DICT
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId as Up

from bot.builds import PROFILES_BY_OPENING, STAGED_PROFILES_BY_OPENING
from bot.builds.profile_compact import expand_compact_profile
from bot.intel.utils.upgrade_catalog import derive_upgrades_from_comp
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.mind.opening_state import require_active_opening_state, set_requested_opening_state


# ===== BEGIN build_catalog.py =====




_REQUIRED_KEYS = {
    "comp_defensive",
    "comp_standard",
    "comp_punish",
    "comp_rush_response",
    "priority_defensive",
    "priority_standard",
    "priority_punish",
    "priority_rush_response",
    "army_supply_milestones_by_mode",
    "unit_count_milestones_by_mode",
    "timing_attacks_by_mode",
    "production_structure_targets_by_mode",
    "production_scale_by_mode",
    "tech_structure_targets_by_mode",
    "tech_timing_milestones_by_mode",
    "pid_tuning_by_mode",
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def resolve_build_profile(*, opening_selected: str, transition_target: str, phase: str = "", scenario: str = "") -> Dict[str, Any]:
    opening = str(opening_selected or "").strip()
    if not opening:
        raise RuntimeError("missing_contract:macro.opening.selected")
    if opening not in PROFILES_BY_OPENING:
        raise RuntimeError(f"missing_contract:build_profile:{opening}")

    phase_name = str(phase or "").strip().upper()
    staged_by_phase = dict(STAGED_PROFILES_BY_OPENING.get(opening, {}) or {})
    if phase_name and phase_name in staged_by_phase:
        selected_profile = deepcopy(staged_by_phase[phase_name])
    else:
        selected_profile = deepcopy(PROFILES_BY_OPENING[opening])

    # New canonical format can provide phase profile with `scenarios`.
    scenario_name = str(scenario or "").strip().upper()
    scenarios = selected_profile.get("scenarios", None)
    if isinstance(scenarios, dict):
        root_transition_overrides = dict(selected_profile.get("transition_overrides", {}) or {})
        root_scenario_overrides = dict(selected_profile.get("scenario_overrides_by_phase", {}) or {})
        chosen = scenarios.get(scenario_name)
        if not isinstance(chosen, dict):
            raise RuntimeError(f"invalid_contract:build_profile:{opening}:missing_scenario:{scenario_name or 'UNKNOWN'}")
        selected_profile = dict(chosen)
        if root_transition_overrides:
            selected_profile["transition_overrides"] = dict(root_transition_overrides)
        if root_scenario_overrides:
            selected_profile["scenario_overrides_by_phase"] = dict(root_scenario_overrides)

    profile = expand_compact_profile(selected_profile)
    if "bank_setpoint_minerals" in profile or "bank_setpoint_gas" in profile:
        raise RuntimeError(f"invalid_contract:build_profile:{opening}:deprecated_bank_fields")
    transition_overrides = dict(profile.pop("transition_overrides", {}) or {})
    transition = str(transition_target or "").strip().upper()
    if transition and transition in transition_overrides:
        profile = _deep_merge(profile, dict(transition_overrides[transition]))
    scenario_overrides = dict(profile.pop("scenario_overrides_by_phase", {}) or {})
    if phase_name and scenario_name:
        phase_over = scenario_overrides.get(phase_name, {})
        if isinstance(phase_over, dict):
            scen_over = phase_over.get(scenario_name, {})
            if isinstance(scen_over, dict):
                profile = _deep_merge(profile, dict(scen_over))
    if "bank_setpoint_minerals" in profile or "bank_setpoint_gas" in profile:
        raise RuntimeError(f"invalid_contract:build_profile:{opening}:deprecated_bank_fields")

    missing = [k for k in _REQUIRED_KEYS if k not in profile]
    if missing:
        raise RuntimeError(f"invalid_contract:build_profile:{opening}:missing:{','.join(sorted(missing))}")

    return profile

# ===== END build_catalog.py =====

# ===== BEGIN i1_macro_mode_intel.py =====




@dataclass(frozen=True)
class MacroModeIntelConfig:
    ttl_s: float = 25.0
    min_confidence: float = 0.65
    earlygame_at_s: float = 220.0
    midgame_at_s: float = 540.0
    lategame_at_s: float = 780.0


def _phase_for_build(*, now: float, opening_done: bool, cfg: MacroModeIntelConfig) -> str:
    if not bool(opening_done):
        return "OPENING"
    if float(now) < float(cfg.earlygame_at_s):
        return "EARLY"
    if float(now) < float(cfg.midgame_at_s):
        return "MID"
    if float(now) < float(cfg.lategame_at_s):
        return "LATE"
    return "LATE"


def _phase_profile_key(phase: str) -> str:
    p = str(phase or "").upper()
    if p == "OPENING":
        return "OPENING"
    if p in {"EARLY", "MID"}:
        return "MIDGAME"
    return "LATEGAME"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(v)))


def _scale_army_supply_milestones(raw: Any, *, scale: float) -> Any:
    if not isinstance(raw, list):
        return raw
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            t = float(item.get("t", 0.0))
            s = float(item.get("supply", 0.0))
        except Exception:
            continue
        out.append({"t": float(t), "supply": max(0.0, float(s) * float(scale))})
    return out


def _scale_unit_count_milestones(raw: Any, *, scale: float) -> Any:
    if not isinstance(raw, list):
        return raw
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        units_raw = item.get("units", {})
        if not isinstance(units_raw, dict):
            continue
        units_out: dict[str, int] = {}
        for n, v in units_raw.items():
            if not isinstance(n, str):
                continue
            try:
                units_out[str(n)] = max(0, int(round(float(v) * float(scale))))
            except Exception:
                continue
        out.append({"t": float(item.get("t", 0.0) or 0.0), "units": dict(units_out)})
    return out


def _apply_seed_adaptive_profile(
    *,
    profile: Dict[str, Any],
    attention: Attention,
    awareness: Awareness,
    now: float,
    phase: str,
) -> tuple[Dict[str, Any], Dict[str, float | str]]:
    out = deepcopy(dict(profile or {}))
    seed = out.get("seed", {})
    if not isinstance(seed, dict):
        seed = {}

    focus_structure = str(seed.get("focus_structure", "BARRACKS") or "BARRACKS").upper()
    gain_supply = float(seed.get("adapt_gain_supply", 0.22) or 0.22)
    gain_units = float(seed.get("adapt_gain_units", 0.26) or 0.26)
    gain_prod = float(seed.get("adapt_gain_production", 0.20) or 0.20)

    minerals = int(getattr(attention.economy, "minerals", 0) or 0)
    bank_target_m = int(awareness.mem.get(K("macro", "control", "bank_target_minerals"), now=now, default=650) or 650)
    bank_target_m = max(250, int(bank_target_m))
    flood = _clamp((float(minerals) - float(bank_target_m)) / float(max(220, bank_target_m)), 0.0, 1.4)

    urgency = int(getattr(attention.combat, "primary_urgency", 0) or 0)
    pressure = _clamp((float(urgency) - 12.0) / 24.0, 0.0, 1.2)
    rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
    aggression_state = str(awareness.mem.get(K("enemy", "aggression", "state"), now=now, default="NONE") or "NONE").upper()
    if rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"} or aggression_state in {"RUSH", "AGGRESSION"}:
        pressure = _clamp(float(pressure) + 0.20, 0.0, 1.2)

    delta = _clamp(float(flood) - float(pressure), -1.2, 1.2)
    supply_scale = _clamp(1.0 + (float(gain_supply) * float(delta)), 0.72, 1.45)
    units_scale = _clamp(1.0 + (float(gain_units) * float(delta)), 0.70, 1.50)
    prod_scale_mul = _clamp(1.0 + (float(gain_prod) * float(delta)), 0.65, 1.55)

    for mode_key in ("army_supply_milestones_by_mode", "unit_count_milestones_by_mode"):
        mode_map = out.get(mode_key, {})
        if not isinstance(mode_map, dict):
            continue
        scaled_map: dict[str, Any] = {}
        for mode, val in mode_map.items():
            if mode_key == "army_supply_milestones_by_mode":
                scaled_map[str(mode)] = _scale_army_supply_milestones(val, scale=float(supply_scale))
            else:
                scaled_map[str(mode)] = _scale_unit_count_milestones(val, scale=float(units_scale))
        out[mode_key] = dict(scaled_map)

    prod_scale_by_mode = out.get("production_scale_by_mode", {})
    if isinstance(prod_scale_by_mode, dict):
        new_map: dict[str, dict[str, float]] = {}
        for mode, lane_cfg in prod_scale_by_mode.items():
            if not isinstance(lane_cfg, dict):
                continue
            lane_out: dict[str, float] = {}
            for lane, val in lane_cfg.items():
                try:
                    lane_out[str(lane)] = max(0.0, float(val) * float(prod_scale_mul))
                except Exception:
                    continue
            new_map[str(mode)] = lane_out
        out["production_scale_by_mode"] = dict(new_map)

    prod_targets_by_mode = out.get("production_structure_targets_by_mode", {})
    if isinstance(prod_targets_by_mode, dict):
        tgt_map: dict[str, dict[str, int]] = {}
        for mode, lane_cfg in prod_targets_by_mode.items():
            if not isinstance(lane_cfg, dict):
                continue
            lane_out = {str(k): max(0, int(v or 0)) for k, v in lane_cfg.items()}
            if float(delta) >= 0.35:
                lane_out[str(focus_structure)] = int(lane_out.get(str(focus_structure), 0)) + 1
            elif float(delta) <= -0.35:
                lane_out[str(focus_structure)] = max(0, int(lane_out.get(str(focus_structure), 0)) - 1)
            tgt_map[str(mode)] = lane_out
        out["production_structure_targets_by_mode"] = dict(tgt_map)

    return out, {
        "flood": float(flood),
        "pressure": float(pressure),
        "delta": float(delta),
        "supply_scale": float(supply_scale),
        "units_scale": float(units_scale),
        "prod_scale_mul": float(prod_scale_mul),
        "focus_structure": str(focus_structure),
        "seed_gain_supply": float(gain_supply),
        "seed_gain_units": float(gain_units),
        "seed_gain_production": float(gain_prod),
        "phase_profile": str(phase),
    }


def derive_macro_mode_intel(
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    cfg: MacroModeIntelConfig = MacroModeIntelConfig(),
) -> dict[str, Any]:
    enemy_kind = awareness.mem.get(K("enemy", "opening", "kind"), now=now, default="NORMAL")
    conf = float(awareness.mem.get(K("enemy", "opening", "confidence"), now=now, default=0.0) or 0.0)
    rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
    aggression_state = str(awareness.mem.get(K("enemy", "aggression", "state"), now=now, default="NONE") or "NONE").upper()
    aggression_source = awareness.mem.get(K("enemy", "aggression", "source"), now=now, default={}) or {}
    if not isinstance(aggression_source, dict):
        aggression_source = {}
    rush_is_early = bool(aggression_source.get("rush_is_early", False))
    rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
    rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
    rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
    rush_tier = str(awareness.mem.get(K("enemy", "rush", "tier"), now=now, default="NONE") or "NONE").upper()
    rush_severity = float(awareness.mem.get(K("enemy", "rush", "severity"), now=now, default=0.0) or 0.0)
    opening_selected, transition_target = require_active_opening_state(awareness=awareness, now=now)
    scout_no_natural_confirmed = bool(
        awareness.mem.get(K("enemy", "rush", "scout_no_natural_confirmed"), now=now, default=False)
    )
    no_natural_structural_confirmed = bool(
        awareness.mem.get(K("enemy", "rush", "no_natural_structural_confirmed"), now=now, default=False)
    )
    rush_last_seen_pressure_t = float(
        awareness.mem.get(K("enemy", "rush", "last_seen_pressure_t"), now=now, default=0.0) or 0.0
    )
    requested_opening = str(opening_selected)
    requested_transition_target = str(transition_target)
    opening_request_reason = "follow_current_opening"
    banshee_harass_done = bool(awareness.mem.get(K("ops", "harass", "banshee", "done"), now=now, default=False))
    opening_done = bool(attention.macro.opening_done)
    phase = _phase_for_build(now=float(now), opening_done=bool(opening_done), cfg=cfg)
    phase_profile = _phase_profile_key(str(phase))
    # Build profile is phase-seeded only. Runtime adaptation handles pressure/flood dynamics.
    scenario = "NORMAL"

    enemy_at_door = bool(
        int(getattr(attention.combat, "primary_urgency", 0) or 0) >= 16
        and int(getattr(attention.combat, "primary_enemy_count", 0) or 0) >= 2
    )
    mecha_should_abort_to_rush_defense = bool(
        scout_no_natural_confirmed
        or no_natural_structural_confirmed
        or rush_state == "CONFIRMED"
        or (
            not bool(opening_done)
            and rush_state == "HOLDING"
        )
        or (
            rush_state == "SUSPECTED"
            and (
                bool(enemy_at_door)
                or (
                    rush_tier in {"HEAVY", "EXTREME"}
                    and float(rush_severity) >= 0.80
                )
            )
        )
    )
    if str(opening_selected) == "MechaOpen" and bool(mecha_should_abort_to_rush_defense):
        requested_opening = "RushDefenseOpen"
        requested_transition_target = "STIM"
        opening_request_reason = "enemy_rush_pressure"
    # Read enemy expansion evidence for accelerated rush-defense exit.
    enemy_build_snapshot = awareness.mem.get(K("enemy", "build", "snapshot"), now=now, default={}) or {}
    if not isinstance(enemy_build_snapshot, dict):
        enemy_build_snapshot = {}
    enemy_bases_visible = int(enemy_build_snapshot.get("bases_visible", 0) or 0)
    enemy_nat_on_ground = bool(enemy_build_snapshot.get("natural_on_ground", False))
    clear_for_s = max(0.0, float(now) - float(rush_last_seen_pressure_t)) if float(rush_last_seen_pressure_t) > 0.0 else 0.0

    # Fast exit: rush is fully cleared (NONE or ENDED) AND enemy has clearly committed to
    # expanding (nat established, 2+ bases visible). Does NOT require opening_done — this
    # handles the case where the bot stayed in RushDefenseOpen past opening completion.
    # HOLDING is intentionally excluded: we must wait for the rush to be over first.
    rush_stable_clear_fast = bool(
        str(opening_selected) == "RushDefenseOpen"
        and enemy_nat_on_ground
        and int(enemy_bases_visible) >= 2
        and rush_state in {"NONE", "ENDED"}
        and not bool(enemy_at_door)
        and float(clear_for_s) >= 18.0
    )
    # Normal exit: opening finished, rush fully cleared, waited enough.
    rush_stable_clear_normal = bool(
        str(opening_selected) == "RushDefenseOpen"
        and bool(attention.macro.opening_done)
        and rush_state in {"NONE", "ENDED"}
        and float(clear_for_s) >= 20.0
    )
    rush_stable_clear = rush_stable_clear_fast or rush_stable_clear_normal
    if rush_stable_clear:
        requested_opening = "BioOpen"
        requested_transition_target = "STIM"
        opening_request_reason = "rush_stable_clear_fast" if rush_stable_clear_fast else "rush_stable_clear"

    set_requested_opening_state(
        awareness=awareness,
        now=now,
        opening=str(requested_opening),
        transition_target=str(requested_transition_target),
        reason=str(opening_request_reason),
        ttl_s=float(cfg.ttl_s),
    )

    effective_opening = str(requested_opening)
    effective_transition_target = str(requested_transition_target)

    profile = resolve_build_profile(
        opening_selected=str(effective_opening),
        transition_target=str(effective_transition_target),
        phase=str(phase_profile),
        scenario=str(scenario),
    )
    profile, adaptive = _apply_seed_adaptive_profile(
        profile=dict(profile),
        attention=attention,
        awareness=awareness,
        now=float(now),
        phase=str(phase_profile),
    )

    rush_detected = bool((rush_is_early and rush_state in {"CONFIRMED", "HOLDING", "SUSPECTED"}) or aggression_state == "RUSH")
    pressure = float(adaptive.get("pressure", 0.0) or 0.0)
    flood = float(adaptive.get("flood", 0.0) or 0.0)
    if rush_stable_clear:
        # Enemy has committed to expanding — do not stay in RUSH_RESPONSE/DEFENSIVE mode.
        # The opening transition to BioOpen was already requested above; mode follows.
        mode = "STANDARD"
    elif rush_tier in {"HEAVY", "EXTREME"}:
        mode = "RUSH_RESPONSE"
    elif rush_detected and float(pressure) >= 0.70:
        mode = "RUSH_RESPONSE"
    elif float(pressure) >= 0.52:
        mode = "DEFENSIVE"
    elif float(flood) >= 0.45:
        mode = "PUNISH"
    else:
        mode = "STANDARD"

    awareness.mem.set(K("macro", "desired", "mode"), value=str(mode), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "phase"), value=str(phase), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "scenario"), value=str(scenario), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "rush", "predicted"), value=bool(rush_detected), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(
        K("macro", "desired", "signals"),
        value={
            "rush_state": str(rush_state),
            "rush_tier": str(rush_tier),
            "rush_severity": float(rush_severity),
            "aggression_state": str(aggression_state),
            "enemy_kind": str(enemy_kind),
            "scenario": str(scenario),
            "confidence": float(conf),
            "opening_selected": str(effective_opening),
            "transition_target": str(transition_target),
            "requested_opening": str(requested_opening),
            "requested_transition_target": str(requested_transition_target),
            "opening_request_reason": str(opening_request_reason),
            "rush_stable_clear": bool(rush_stable_clear),
            "rush_stable_clear_fast": bool(rush_stable_clear_fast),
            "enemy_nat_on_ground": bool(enemy_nat_on_ground),
            "enemy_bases_visible": int(enemy_bases_visible),
            "clear_for_s": float(round(clear_for_s, 1)),
            "banshee_harass_done": bool(banshee_harass_done),
            "build_phase": str(phase),
            "phase_profile": str(phase_profile),
            "rush_detected": bool(rush_detected),
            "adaptive": dict(adaptive),
        },
        now=now,
        ttl=float(cfg.ttl_s),
    )
    awareness.mem.set(K("macro", "desired", "last_update_t"), value=float(now), now=now, ttl=None)

    return {
        "mode": str(mode),
        "profile": dict(profile),
        "opening_selected": str(effective_opening),
        "transition_target": str(effective_transition_target),
        "requested_opening": str(requested_opening),
        "requested_transition_target": str(requested_transition_target),
        "banshee_harass_done": bool(banshee_harass_done),
        "build_phase": str(phase),
        "phase_profile": str(phase_profile),
        "scenario": str(scenario),
        "rush_detected": bool(rush_detected),
        "enemy_kind": str(enemy_kind),
        "confidence": float(conf),
        "rush_state": str(rush_state),
        "rush_tier": str(rush_tier),
        "rush_severity": float(rush_severity),
        "aggression_state": str(aggression_state),
        "adaptive": dict(adaptive),
    }

# ===== END i1_macro_mode_intel.py =====

# ===== BEGIN i2_army_comp_intel.py =====





@dataclass(frozen=True)
class ArmyCompIntelConfig:
    ttl_s: float = 25.0
    log_interval_s: float = 8.0


def _normalize(comp: dict[str, float]) -> dict[str, float]:
    total = float(sum(float(v) for v in comp.values()))
    if total <= 0.0:
        return dict(comp)
    return {str(k): float(v) / total for k, v in comp.items()}


def _prepend_unique(items: list[str], head: str) -> list[str]:
    if not head:
        return list(items)
    out = [str(head)]
    for it in items:
        s = str(it)
        if s == str(head):
            continue
        out.append(s)
    return out


def _inject_unit_comp_bias(comp: dict[str, float], *, unit_name: str, weight: float = 0.12) -> dict[str, float]:
    out = dict(comp)
    if unit_name in out:
        return out
    out[str(unit_name)] = float(weight)
    return _normalize(out)


def _boost_unit_comp_bias(comp: dict[str, float], *, unit_name: str, weight: float) -> dict[str, float]:
    out = dict(comp)
    out[str(unit_name)] = float(out.get(str(unit_name), 0.0) or 0.0) + float(weight)
    return _normalize(out)


def _scale_unit_comp_bias(comp: dict[str, float], *, unit_name: str, factor: float) -> dict[str, float]:
    out = dict(comp)
    if str(unit_name) not in out:
        return _normalize(out)
    out[str(unit_name)] = max(0.0, float(out.get(str(unit_name), 0.0) or 0.0) * float(factor))
    return _normalize(out)


def _controller_comp(comp: dict[str, float], priority_units: list[str]) -> dict[str, dict[str, float | int]]:
    ordered = sorted(comp.items(), key=lambda kv: float(kv[1]), reverse=True)
    if priority_units:
        idx = {str(name): i for i, name in enumerate(priority_units)}
        ordered.sort(key=lambda kv: (idx.get(str(kv[0]), 999), -float(kv[1])))
    out: dict[str, dict[str, float | int]] = {}
    for i, (unit_name, proportion) in enumerate(ordered):
        out[str(unit_name)] = {"proportion": float(proportion), "priority": int(i)}
    return out


def _mode_value(cfg_map: dict[str, Any], *, mode: str, key: str) -> Any:
    out = cfg_map.get(str(mode))
    if out is None:
        raise RuntimeError(f"missing_contract:macro.desired.{key}:{mode}")
    return out


def _unit_reserve_cost(unit_name: str) -> tuple[int, int]:
    if not str(unit_name):
        return 0, 0
    try:
        uid = getattr(U, str(unit_name))
        cost = COST_DICT.get(uid, None)
        if cost is not None:
            return int(getattr(cost, "minerals", 0) or 0), int(getattr(cost, "vespene", 0) or 0)
    except Exception:
        pass
    return 0, 0


def _unit_is_bias_ready(*, attention: Attention, unit_name: str) -> bool:
    name = str(unit_name).upper()
    if name in {"SIEGETANK", "CYCLONE"}:
        return bool(int(getattr(attention.macro, "factory_techlab", 0) or 0) > 0)
    if name in {"THOR", "BATTLECRUISER"}:
        return False
    if name in {"MARAUDER"}:
        return bool(int(getattr(attention.macro, "barracks_techlab", 0) or 0) > 0)
    if name in {"GHOST"}:
        ready = dict(getattr(attention.economy, "units_ready", {}) or {})
        return bool(int(getattr(attention.macro, "barracks_techlab", 0) or 0) > 0 and int(ready.get(U.GHOSTACADEMY, 0) or 0) > 0)
    if name in {"BANSHEE", "RAVEN"}:
        return bool(int(getattr(attention.macro, "starport_techlab", 0) or 0) > 0)
    if name in {"MEDIVAC", "VIKINGFIGHTER", "LIBERATOR"}:
        ready = dict(getattr(attention.economy, "units_ready", {}) or {})
        return bool(int(ready.get(U.STARPORT, 0) or 0) > 0)
    return True


def _apply_gas_overflow_unit_bias(
    comp: dict[str, float],
    *,
    priority_units: list[str],
    attention: Attention,
    now: float,
    awareness: Awareness,
    opening_selected: str,
    enemy_at_door: bool,
    rush_active: bool,
    aggression_state: str,
) -> tuple[dict[str, float], list[str]]:
    gas = int(getattr(attention.economy, "gas", 0) or 0)
    minerals = int(getattr(attention.economy, "minerals", 0) or 0)
    bank_target_g = int(awareness.mem.get(K("macro", "desired", "bank_target_gas"), now=now, default=220) or 220)
    overflow = max(0, int(gas) - int(bank_target_g))
    if overflow <= 90 or bool(enemy_at_door) or bool(rush_active) or str(aggression_state) in {"RUSH", "AGGRESSION"}:
        return dict(comp), list(priority_units)

    candidates: list[tuple[float, str, int, int]] = []
    for unit_name, weight in dict(comp).items():
        if float(weight) <= 0.0:
            continue
        m_cost, g_cost = _unit_reserve_cost(str(unit_name))
        if g_cost < 50:
            continue
        if not _unit_is_bias_ready(attention=attention, unit_name=str(unit_name)):
            continue
        if minerals < max(75, int(m_cost * 0.85)):
            continue
        gas_ratio = float(g_cost) / max(1.0, float(m_cost))
        score = (0.60 * float(g_cost)) + (0.25 * float(gas_ratio)) + (0.15 * float(weight * 100.0))
        candidates.append((float(score), str(unit_name), int(m_cost), int(g_cost)))
    if not candidates:
        return dict(comp), list(priority_units)

    candidates.sort(reverse=True)
    chosen = str(candidates[0][1])
    boost = 0.10 if overflow < 220 else 0.18
    out_comp = _boost_unit_comp_bias(dict(comp), unit_name=str(chosen), weight=float(boost))
    out_prio = _prepend_unique(list(priority_units), str(chosen))

    if str(opening_selected) == "MechaOpen" and chosen == "SIEGETANK" and float(out_comp.get("HELLION", 0.0) or 0.0) > 0.0:
        damp = 0.78 if overflow < 220 else 0.60
        out_comp = _scale_unit_comp_bias(out_comp, unit_name="HELLION", factor=float(damp))
    return dict(out_comp), list(out_prio)


def _infer_bank_targets(*, comp: dict[str, float], mode: str) -> tuple[int, int]:
    total_w = 0.0
    avg_m = 0.0
    avg_g = 0.0
    for unit_name, w in dict(comp or {}).items():
        weight = max(0.0, float(w))
        if weight <= 0.0:
            continue
        total_w += float(weight)
        m, g = _unit_reserve_cost(str(unit_name))
        avg_m += float(m) * float(weight)
        avg_g += float(g) * float(weight)
    if total_w > 1e-6:
        avg_m /= float(total_w)
        avg_g /= float(total_w)
    gas_ratio = float(avg_g) / max(1.0, float(avg_m))
    mineral_factor = max(0.0, min(1.4, float(avg_m) / 120.0))
    tech_factor = max(0.0, min(1.4, float(avg_g) / 90.0))

    base_m = 420.0 + (160.0 * mineral_factor) + (80.0 * max(0.0, 1.0 - gas_ratio))
    base_g = 110.0 + (170.0 * tech_factor) + (90.0 * min(1.0, gas_ratio))

    mode_mul = {
        "RUSH_RESPONSE": (0.78, 0.82),
        "DEFENSIVE": (0.88, 0.90),
        "STANDARD": (1.00, 1.00),
        "PUNISH": (1.20, 1.15),
    }.get(str(mode).upper(), (1.0, 1.0))
    bank_m = int(max(300, min(980, round(base_m * float(mode_mul[0])))))
    bank_g = int(max(90, min(520, round(base_g * float(mode_mul[1])))))
    return int(bank_m), int(bank_g)


def _clamp_low_base_production(
    *,
    production_structure_targets: dict[str, int],
    production_scale: dict[str, float],
    bases_now: int,
    nat_is_mining: bool,
    rush_state: str,
    opening_selected: str,
) -> tuple[dict[str, int], dict[str, float]]:
    targets = {str(k): max(0, int(v or 0)) for k, v in dict(production_structure_targets).items()}
    scales = {str(k): max(0.0, float(v or 0.0)) for k, v in dict(production_scale).items()}
    rush_active = str(rush_state).upper() in {"SUSPECTED", "CONFIRMED", "HOLDING"}
    if rush_active:
        return targets, scales

    if int(bases_now) < 2 or not bool(nat_is_mining):
        cap_targets = {"BARRACKS": 2, "FACTORY": 1, "STARPORT": 0}
        cap_scales = {"BARRACKS": 0.95, "FACTORY": 0.45, "STARPORT": 0.0}
    elif int(bases_now) == 2:
        if str(opening_selected) == "MechaOpen":
            cap_targets = {"BARRACKS": 3, "FACTORY": 2, "STARPORT": 1}
            cap_scales = {"BARRACKS": 1.10, "FACTORY": 0.85, "STARPORT": 0.55}
        else:
            cap_targets = {"BARRACKS": 4, "FACTORY": 1, "STARPORT": 1}
            cap_scales = {"BARRACKS": 1.45, "FACTORY": 0.55, "STARPORT": 0.55}
    else:
        return targets, scales

    for name, cap in cap_targets.items():
        targets[str(name)] = min(int(targets.get(str(name), 0) or 0), int(cap))
    for name, cap in cap_scales.items():
        scales[str(name)] = min(float(scales.get(str(name), 0.0) or 0.0), float(cap))
    return targets, scales


def _harass_missing_unit_from_cooldown(*, awareness: Awareness, now: float) -> str | None:
    snap = awareness.mem.snapshot(now=now, prefix=K("ops", "cooldown"), max_age=90.0)
    latest_t = -1.0
    missing: str | None = None
    for sk, entry in snap.items():
        parts = sk.split(":")
        if len(parts) < 4 or parts[0] != "ops" or parts[1] != "cooldown" or parts[-1] != "reason":
            continue
        proposal_id = ":".join(parts[2:-1])
        if not proposal_id.startswith("harass_planner:"):
            continue
        reason = str(entry.get("value") or "")
        t = float(entry.get("t") or 0.0)
        unit = ""
        if "reaper" in reason:
            unit = "REAPER"
        elif "hellion" in reason:
            unit = "HELLION"
        elif "banshee" in reason:
            unit = "BANSHEE"
        if unit and t > latest_t:
            latest_t = t
            missing = unit
    return missing


def _unit_targets_at_time(*, milestones: list[dict[str, Any]], now: float) -> dict[str, float]:
    points: list[tuple[float, dict[str, float]]] = []
    for item in milestones:
        if not isinstance(item, dict):
            continue
        try:
            t = float(item.get("t", 0.0))
        except Exception:
            continue
        units_raw = item.get("units", {})
        if not isinstance(units_raw, dict):
            continue
        units: dict[str, float] = {}
        for name, val in units_raw.items():
            if not isinstance(name, str):
                continue
            try:
                units[str(name)] = max(0.0, float(val))
            except Exception:
                continue
        points.append((t, units))
    if not points:
        return {}
    points.sort(key=lambda x: x[0])
    t_now = float(now)
    if t_now <= points[0][0]:
        return dict(points[0][1])
    for i in range(1, len(points)):
        t0, u0 = points[i - 1]
        t1, u1 = points[i]
        if t_now <= t1:
            a = max(0.0, min(1.0, (t_now - t0) / max(1e-6, t1 - t0)))
            names = set(u0.keys()) | set(u1.keys())
            out: dict[str, float] = {}
            for n in names:
                v0 = float(u0.get(n, 0.0))
                v1 = float(u1.get(n, 0.0))
                out[str(n)] = float(v0 + (a * (v1 - v0)))
            return out
    return dict(points[-1][1])


def _largest_unit_shortfall(*, attention: Attention, unit_targets: dict[str, float]) -> tuple[str | None, float]:
    if not unit_targets:
        return None, 0.0
    ready = dict(attention.economy.units_ready or {})
    best_name: str | None = None
    best_gap = 0.0
    for name, target in unit_targets.items():
        if float(target) <= 0.0:
            continue
        try:
            uid = getattr(U, str(name))
            cur = float(int(ready.get(uid, 0) or 0))
        except Exception:
            continue
        gap = max(0.0, float(target) - cur)
        if gap > best_gap:
            best_gap = float(gap)
            best_name = str(name)
    return best_name, float(best_gap)


def derive_army_comp_intel(
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    profile: dict[str, Any],
    mode: str,
    opening_selected: str,
    banshee_harass_done: bool,
    cfg: ArmyCompIntelConfig = ArmyCompIntelConfig(),
) -> dict[str, Any]:
    comp_by_mode = {
        "RUSH_RESPONSE": _normalize(dict(profile["comp_rush_response"])),
        "DEFENSIVE": _normalize(dict(profile["comp_defensive"])),
        "PUNISH": _normalize(dict(profile["comp_punish"])),
        "STANDARD": _normalize(dict(profile["comp_standard"])),
    }
    prio_by_mode = {
        "RUSH_RESPONSE": [str(x) for x in list(profile["priority_rush_response"])],
        "DEFENSIVE": [str(x) for x in list(profile["priority_defensive"])],
        "PUNISH": [str(x) for x in list(profile["priority_punish"])],
        "STANDARD": [str(x) for x in list(profile["priority_standard"])],
    }
    comp = dict(comp_by_mode.get(str(mode), comp_by_mode["STANDARD"]))
    priority_units = list(prio_by_mode.get(str(mode), prio_by_mode["STANDARD"]))

    rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
    rush_tier = str(awareness.mem.get(K("enemy", "rush", "tier"), now=now, default="NONE") or "NONE").upper()
    rush_severity = float(awareness.mem.get(K("enemy", "rush", "severity"), now=now, default=0.0) or 0.0)
    aggression_state = str(awareness.mem.get(K("enemy", "aggression", "state"), now=now, default="NONE") or "NONE").upper()
    rush_active = rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}
    factory_techlab_ready = int(getattr(attention.macro, "factory_techlab", 0) or 0) > 0
    enemy_at_door = bool(
        int(getattr(attention.combat, "primary_urgency", 0) or 0) >= 16
        and int(getattr(attention.combat, "primary_enemy_count", 0) or 0) >= 2
    )
    harass_bias_blocked = bool(
        rush_active
        or bool(enemy_at_door)
        or aggression_state in {"RUSH", "AGGRESSION"}
    )

    missing_harass_unit = _harass_missing_unit_from_cooldown(awareness=awareness, now=now)
    if not bool(harass_bias_blocked) and missing_harass_unit is not None:
        priority_units = _prepend_unique(priority_units, missing_harass_unit)
        comp = _inject_unit_comp_bias(comp, unit_name=str(missing_harass_unit), weight=0.12)

    mecha_emergency_hellions = bool(
        str(opening_selected) == "MechaOpen"
        and not bool(factory_techlab_ready)
        and bool(enemy_at_door)
    )
    if (
        str(opening_selected) == "MechaOpen"
        and not bool(factory_techlab_ready)
        and not bool(enemy_at_door)
    ):
        comp.pop("HELLION", None)
    if str(opening_selected) == "MechaOpen" and rush_tier in {"HEAVY", "EXTREME"}:
        priority_units = _prepend_unique(priority_units, "MARINE")
        comp = _boost_unit_comp_bias(
            comp,
            unit_name="MARINE",
            weight=(0.22 if rush_tier == "HEAVY" else 0.34),
        )
        if float(rush_severity) >= 0.90:
            priority_units = _prepend_unique(priority_units, "MARAUDER")

    wants_banshee_path = bool("BANSHEE" in set(str(x) for x in priority_units) or float(comp.get("BANSHEE", 0.0) or 0.0) >= 0.08)
    if bool(wants_banshee_path) and not bool(banshee_harass_done):
        priority_units = _prepend_unique(priority_units, "BANSHEE")
        if bool(mecha_emergency_hellions):
            priority_units = _prepend_unique(priority_units, "HELLION")
            comp = _inject_unit_comp_bias(comp, unit_name="HELLION", weight=0.16)
        comp = _inject_unit_comp_bias(comp, unit_name="BANSHEE", weight=0.14)

    unit_milestones = list(_mode_value(dict(profile["unit_count_milestones_by_mode"]), mode=str(mode), key="unit_count_milestones"))
    unit_targets_now = _unit_targets_at_time(milestones=unit_milestones, now=float(now))
    lag_unit_name, lag_unit_gap = _largest_unit_shortfall(attention=attention, unit_targets=unit_targets_now)
    allow_lagging_bias = True
    if str(opening_selected) == "MechaOpen":
        allowed_mech_air_lag_units = {"CYCLONE", "HELLION", "SIEGETANK", "BANSHEE", "LIBERATOR", "THOR"}
        allow_lagging_bias = str(lag_unit_name or "") in allowed_mech_air_lag_units
        if str(lag_unit_name or "") == "HELLION" and not bool(mecha_emergency_hellions):
            allow_lagging_bias = False
    if allow_lagging_bias and lag_unit_name is not None and float(lag_unit_gap) > 0.0:
        priority_units = _prepend_unique(priority_units, str(lag_unit_name))
        comp = _inject_unit_comp_bias(comp, unit_name=str(lag_unit_name), weight=0.18)
    if str(opening_selected) == "MechaOpen" and not bool(mecha_emergency_hellions):
        priority_units = _prepend_unique(priority_units, "SIEGETANK")
        comp = _boost_unit_comp_bias(comp, unit_name="SIEGETANK", weight=0.14)

    if str(opening_selected) == "RushDefenseOpen" and rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}:
        allowed_units = {"MARINE", "MARAUDER", "SIEGETANK"}
        comp = {str(name): float(weight) for name, weight in comp.items() if str(name) in allowed_units and float(weight) > 0.0}
        comp = _boost_unit_comp_bias(comp, unit_name="SIEGETANK", weight=0.16)
        comp = _boost_unit_comp_bias(comp, unit_name="MARINE", weight=0.10)
        # Ares SpawnController stops on an unaffordable higher-priority unit.
        # Keep Marines ahead of Tanks during rush defense so idle Barracks still
        # spend minerals when Factory tech/gas is not ready.
        priority_units = ["MARINE", "SIEGETANK", "MARAUDER"] + [
            str(unit_name)
            for unit_name in priority_units
            if str(unit_name) in allowed_units and str(unit_name) not in {"MARINE", "SIEGETANK", "MARAUDER"}
        ]

    comp, priority_units = _apply_gas_overflow_unit_bias(
        comp=dict(comp),
        priority_units=list(priority_units),
        attention=attention,
        now=float(now),
        awareness=awareness,
        opening_selected=str(opening_selected),
        enemy_at_door=bool(enemy_at_door),
        rush_active=bool(rush_active),
        aggression_state=str(aggression_state),
    )

    comp = _normalize(comp)
    controller_comp = _controller_comp(comp=comp, priority_units=priority_units)
    top_unit = str(priority_units[0]) if priority_units else ""
    reserve_m, reserve_g = _unit_reserve_cost(str(top_unit))

    bank_target_m, bank_target_g = _infer_bank_targets(comp=comp, mode=str(mode))

    army_supply_milestones = list(_mode_value(dict(profile["army_supply_milestones_by_mode"]), mode=str(mode), key="army_supply_milestones"))
    timing_attacks = list(_mode_value(dict(profile["timing_attacks_by_mode"]), mode=str(mode), key="timing_attacks"))
    pid_tuning = dict(_mode_value(dict(profile["pid_tuning_by_mode"]), mode=str(mode), key="pid_tuning"))

    awareness.mem.set(K("macro", "desired", "comp"), value=dict(comp), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "controller_comp"), value=dict(controller_comp), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "army_comp"), value=dict(controller_comp), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "priority_units"), value=list(priority_units), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "reserve_unit"), value=str(top_unit), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "reserve_minerals"), value=int(reserve_m), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "reserve_gas"), value=int(reserve_g), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "bank_target_minerals"), value=int(bank_target_m), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "bank_target_gas"), value=int(bank_target_g), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "pid_tuning"), value=dict(pid_tuning), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "army_supply_milestones"), value=list(army_supply_milestones), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "unit_count_milestones"), value=list(unit_milestones), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "timing_attacks"), value=list(timing_attacks), now=now, ttl=float(cfg.ttl_s))

    return {
        "comp": dict(comp),
        "controller_comp": dict(controller_comp),
        "priority_units": list(priority_units),
        "top_unit": str(top_unit),
        "reserve_minerals": int(reserve_m),
        "reserve_gas": int(reserve_g),
        "bank_target_minerals": int(bank_target_m),
        "bank_target_gas": int(bank_target_g),
        "lagging_unit": str(lag_unit_name or ""),
        "lagging_unit_gap": float(lag_unit_gap),
    }

# ===== END i2_army_comp_intel.py =====

# ===== BEGIN i3_tech_intel.py =====





@dataclass(frozen=True)
class TechIntelConfig:
    ttl_s: float = 25.0


def _upgrade_names_from_comp(*, comp: dict[str, float], reserve_unit: str) -> list[str]:
    return derive_upgrades_from_comp(comp=dict(comp), reserve_unit=str(reserve_unit))


def derive_tech_intel(
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    profile: dict[str, Any],
    mode: str,
    opening_selected: str,
    comp: dict[str, float],
    reserve_unit: str,
    cfg: TechIntelConfig = TechIntelConfig(),
) -> dict[str, Any]:
    def _due_structures_by_time(*, milestones: list[dict[str, Any]], now_t: float) -> dict[str, int]:
        due: dict[str, int] = {}
        for step in milestones:
            if not isinstance(step, dict):
                continue
            try:
                t = float(step.get("t", 0.0) or 0.0)
            except Exception:
                continue
            if float(t) > float(now_t):
                continue
            sraw = step.get("structures", {})
            if not isinstance(sraw, dict):
                continue
            for n, v in sraw.items():
                if not isinstance(n, str):
                    continue
                try:
                    tgt = max(0, int(v or 0))
                except Exception:
                    continue
                prev = int(due.get(str(n), 0))
                if tgt > prev:
                    due[str(n)] = int(tgt)
        return due

    def _merge_upgrade_lists(primary: list[str], secondary: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for name in list(primary) + list(secondary):
            s = str(name)
            if s in seen or getattr(Up, s, None) is None:
                continue
            seen.add(s)
            out.append(s)
        return out

    production_structure_targets = dict(dict(profile["production_structure_targets_by_mode"]).get(str(mode), {}))
    if not isinstance(production_structure_targets, dict):
        raise RuntimeError(f"invalid_contract:macro.desired.production_structure_targets:{mode}")
    production_scale = dict(dict(profile["production_scale_by_mode"]).get(str(mode), {}))
    if not isinstance(production_scale, dict):
        raise RuntimeError(f"invalid_contract:macro.desired.production_scale:{mode}")
    tech_structure_targets = dict(dict(profile["tech_structure_targets_by_mode"]).get(str(mode), {}))
    if not isinstance(tech_structure_targets, dict):
        raise RuntimeError(f"invalid_contract:macro.desired.tech_structure_targets:{mode}")
    tech_timing_milestones = list(dict(profile["tech_timing_milestones_by_mode"]).get(str(mode), []))
    if not isinstance(tech_timing_milestones, list):
        raise RuntimeError(f"invalid_contract:macro.desired.tech_timing_milestones:{mode}")

    upgrades = _upgrade_names_from_comp(comp=dict(comp), reserve_unit=str(reserve_unit))
    milestone_upgrades: list[str] = []
    for step in tech_timing_milestones:
        if not isinstance(step, dict):
            continue
        raw = step.get("upgrades", [])
        if not isinstance(raw, list):
            continue
        milestone_upgrades.extend([str(x) for x in raw if isinstance(x, str)])
    upgrades = _merge_upgrade_lists(upgrades, milestone_upgrades)
    rush_tier = str(awareness.mem.get(K("enemy", "rush", "tier"), now=now, default="NONE") or "NONE").upper()
    rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
    bases_now = int(getattr(attention.macro, "bases_total", 0) or 0)
    our_bases = awareness.mem.get(K("intel", "our_bases", "registry"), now=now, default={}) or {}
    if not isinstance(our_bases, dict):
        our_bases = {}
    nat_base = dict(our_bases.get("NATURAL", {})) if isinstance(our_bases.get("NATURAL", {}), dict) else {}
    nat_state = str(nat_base.get("state", "") or "").upper()
    nat_owned = bool(nat_base.get("owned", False) or nat_base.get("townhall_tag"))
    nat_is_mining = bool(nat_base.get("is_mining", False))
    natural_unresolved = bool(
        int(bases_now) < 2
        and (not bool(nat_owned) or nat_state not in {"ESTABLISHED", "SECURING"} or not bool(nat_is_mining))
    )
    addon_targets: dict[str, int] = {}
    if float(comp.get("SIEGETANK", 0.0) or 0.0) > 0.0 or float(comp.get("CYCLONE", 0.0) or 0.0) > 0.0:
        addon_targets["FACTORYTECHLAB"] = 1
    if float(comp.get("BANSHEE", 0.0) or 0.0) > 0.0:
        addon_targets["STARPORTTECHLAB"] = 1
    if opening_selected == "MechaOpen":
        blocked_bio = {
            "STIMPACK",
            "SHIELDWALL",
            "PUNISHERGRENADES",
            "TERRANINFANTRYWEAPONSLEVEL1",
            "TERRANINFANTRYARMORSLEVEL1",
            "TERRANINFANTRYWEAPONSLEVEL2",
            "TERRANINFANTRYARMORSLEVEL2",
            "TERRANINFANTRYWEAPONSLEVEL3",
            "TERRANINFANTRYARMORSLEVEL3",
        }
        upgrades = [u for u in list(upgrades) if str(u) not in blocked_bio]
        if not upgrades:
            upgrades = [
                "BANSHEECLOAK",
                "TERRANVEHICLEWEAPONSLEVEL1",
                "TERRANVEHICLEANDSHIPARMORSLEVEL1",
                "TERRANSHIPWEAPONSLEVEL1",
            ]
        if rush_tier in {"HEAVY", "EXTREME"}:
            barracks_floor = 2 if rush_tier == "HEAVY" else 3
            barracks_scale_floor = 0.55 if rush_tier == "HEAVY" else 0.90
            production_structure_targets["BARRACKS"] = max(
                int(production_structure_targets.get("BARRACKS", 0) or 0),
                int(barracks_floor),
            )
            production_scale["BARRACKS"] = max(
                float(production_scale.get("BARRACKS", 0.0) or 0.0),
                float(barracks_scale_floor),
            )
    if opening_selected == "RushDefenseOpen" and rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}:
        upgrades = []
        tech_structure_targets = {}
        tech_timing_milestones = []
        addon_targets["BARRACKSREACTOR"] = max(1, int(addon_targets.get("BARRACKSREACTOR", 0) or 0))
        addon_targets["FACTORYTECHLAB"] = max(1, int(addon_targets.get("FACTORYTECHLAB", 0) or 0))
        barracks_floor = 3 if rush_tier in {"LIGHT", "MEDIUM", "NONE"} else 4
        barracks_scale_floor = 1.20 if rush_tier in {"LIGHT", "MEDIUM", "NONE"} else 1.55
        production_structure_targets["BARRACKS"] = max(
            int(production_structure_targets.get("BARRACKS", 0) or 0),
            int(barracks_floor),
        )
        production_scale["BARRACKS"] = max(
            float(production_scale.get("BARRACKS", 0.0) or 0.0),
            float(barracks_scale_floor),
        )
        production_structure_targets["FACTORY"] = max(
            int(production_structure_targets.get("FACTORY", 0) or 0),
            1,
        )
        production_structure_targets["STARPORT"] = 0
        production_scale["STARPORT"] = 0.0
    if opening_selected == "RushDefenseOpen" and natural_unresolved:
        if rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}:
            # While the natural is unresolved under rush pressure, we still need
            # enough on-base production to dump minerals into immediate defense.
            # Keep starport off, but do not choke barracks/factory throughput.
            production_structure_targets["BARRACKS"] = max(
                int(production_structure_targets.get("BARRACKS", 0) or 0),
                3 if rush_tier in {"LIGHT", "MEDIUM", "NONE"} else 4,
            )
            production_structure_targets["FACTORY"] = max(
                int(production_structure_targets.get("FACTORY", 0) or 0),
                1,
            )
            production_structure_targets["STARPORT"] = 0
            production_scale["BARRACKS"] = max(
                float(production_scale.get("BARRACKS", 0.0) or 0.0),
                1.10 if rush_tier in {"LIGHT", "MEDIUM", "NONE"} else 1.40,
            )
            production_scale["FACTORY"] = max(
                float(production_scale.get("FACTORY", 0.0) or 0.0),
                0.35,
            )
            production_scale["STARPORT"] = 0.0
        else:
            production_structure_targets["BARRACKS"] = min(int(production_structure_targets.get("BARRACKS", 0) or 0), 2)
            production_structure_targets["FACTORY"] = min(int(production_structure_targets.get("FACTORY", 0) or 0), 1)
            production_structure_targets["STARPORT"] = 0
            production_scale["BARRACKS"] = min(float(production_scale.get("BARRACKS", 0.0) or 0.0), 0.85)
            production_scale["FACTORY"] = min(float(production_scale.get("FACTORY", 0.0) or 0.0), 0.35)
            production_scale["STARPORT"] = 0.0
    production_structure_targets, production_scale = _clamp_low_base_production(
        production_structure_targets=dict(production_structure_targets),
        production_scale=dict(production_scale),
        bases_now=int(bases_now),
        nat_is_mining=bool(nat_is_mining),
        rush_state=str(rush_state),
        opening_selected=str(opening_selected),
    )
    due_structures = _due_structures_by_time(milestones=tech_timing_milestones, now_t=float(now))
    # Contract: structures in tech_targets are due-by-time; phase cap stays in tech_structure_targets.
    tech_targets = {"upgrades": list(upgrades), "structures": dict(due_structures)}
    construction_targets = {
        "production_structures": dict(production_structure_targets),
        "tech_structures": dict(tech_structure_targets),
    }

    awareness.mem.set(
        K("macro", "desired", "production_structure_targets"),
        value=dict(production_structure_targets),
        now=now,
        ttl=float(cfg.ttl_s),
    )
    awareness.mem.set(
        K("macro", "desired", "production_scale"),
        value=dict(production_scale),
        now=now,
        ttl=float(cfg.ttl_s),
    )
    awareness.mem.set(K("macro", "desired", "addon_targets"), value=dict(addon_targets), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "tech_structure_targets"), value=dict(tech_structure_targets), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "tech_timing_milestones"), value=list(tech_timing_milestones), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "tech_targets"), value=dict(tech_targets), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "construction_targets"), value=dict(construction_targets), now=now, ttl=float(cfg.ttl_s))
    return {
        "production_structure_targets": dict(production_structure_targets),
        "production_scale": dict(production_scale),
        "addon_targets": dict(addon_targets),
        "tech_structure_targets": dict(tech_structure_targets),
        "tech_timing_milestones": list(tech_timing_milestones),
        "upgrades": list(upgrades),
    }

# ===== END i3_tech_intel.py =====

# ===== BEGIN i4_macro_pipeline_intel.py =====




@dataclass(frozen=True)
class MyArmyCompositionConfig:
    ttl_s: float = 25.0
    min_confidence: float = 0.55
    log_interval_s: float = 8.0
    mode: MacroModeIntelConfig = field(default_factory=MacroModeIntelConfig)
    army: ArmyCompIntelConfig = field(default_factory=ArmyCompIntelConfig)
    tech: TechIntelConfig = field(default_factory=TechIntelConfig)


def derive_my_army_composition_intel(
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    cfg: MyArmyCompositionConfig = MyArmyCompositionConfig(),
) -> None:
    mode_ctx = derive_macro_mode_intel(
        awareness=awareness,
        attention=attention,
        now=now,
        cfg=MacroModeIntelConfig(ttl_s=float(cfg.ttl_s), min_confidence=float(cfg.min_confidence)),
    )
    army_ctx = derive_army_comp_intel(
        awareness=awareness,
        attention=attention,
        now=now,
        profile=dict(mode_ctx["profile"]),
        mode=str(mode_ctx["mode"]),
        opening_selected=str(mode_ctx["opening_selected"]),
        banshee_harass_done=bool(mode_ctx["banshee_harass_done"]),
        cfg=ArmyCompIntelConfig(ttl_s=float(cfg.ttl_s), log_interval_s=float(cfg.log_interval_s)),
    )
    tech_ctx = derive_tech_intel(
        awareness=awareness,
        attention=attention,
        now=now,
        profile=dict(mode_ctx["profile"]),
        mode=str(mode_ctx["mode"]),
        opening_selected=str(mode_ctx["opening_selected"]),
        comp=dict(army_ctx["comp"]),
        reserve_unit=str(army_ctx["top_unit"]),
        cfg=TechIntelConfig(ttl_s=float(cfg.ttl_s)),
    )

    signals = dict(awareness.mem.get(K("macro", "desired", "signals"), now=now, default={}) or {})
    signals.update(
        {
            "lagging_unit": str(army_ctx["lagging_unit"]),
            "lagging_unit_gap": float(round(float(army_ctx["lagging_unit_gap"]), 2)),
            "bank_target_minerals": int(army_ctx["bank_target_minerals"]),
            "bank_target_gas": int(army_ctx["bank_target_gas"]),
            "tech_upgrade_count": int(len(tech_ctx["upgrades"])),
        }
    )
    awareness.mem.set(K("macro", "desired", "signals"), value=dict(signals), now=now, ttl=float(cfg.ttl_s))

    last_emit = float(awareness.mem.get(K("intel", "my_comp", "last_emit_t"), now=now, default=0.0) or 0.0)
    if (float(now) - float(last_emit)) >= float(cfg.log_interval_s):
        awareness.mem.set(K("intel", "my_comp", "last_emit_t"), value=float(now), now=now, ttl=None)
        if awareness.log is not None:
            awareness.log.emit(
                "my_comp_intel",
                {
                    "t": round(float(now), 2),
                    "mode": str(mode_ctx["mode"]),
                    "enemy_kind": str(mode_ctx["enemy_kind"]),
                    "enemy_conf": round(float(mode_ctx["confidence"]), 3),
                    "rush_state": str(mode_ctx["rush_state"]),
                    "opening_selected": str(mode_ctx["opening_selected"]),
                    "transition_target": str(mode_ctx["transition_target"]),
                    "priority_units": list(army_ctx["priority_units"][:5]),
                    "reserve_unit": str(army_ctx["top_unit"]),
                    "reserve_minerals": int(army_ctx["reserve_minerals"]),
                    "reserve_gas": int(army_ctx["reserve_gas"]),
                    "bank_target_minerals": int(army_ctx["bank_target_minerals"]),
                    "bank_target_gas": int(army_ctx["bank_target_gas"]),
                    "lagging_unit": str(army_ctx["lagging_unit"]),
                    "lagging_unit_gap": round(float(army_ctx["lagging_unit_gap"]), 2),
                    "tech_upgrades_head": list(tech_ctx["upgrades"][:5]),
                },
                meta={"module": "intel", "component": "intel.my_comp"},
            )

# ===== END i4_macro_pipeline_intel.py =====


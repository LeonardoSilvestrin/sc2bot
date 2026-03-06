from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


_MODES = ("DEFENSIVE", "STANDARD", "PUNISH", "RUSH_RESPONSE")
_SCENARIOS = ("AGGRESSIVE", "NORMAL", "GREEDY")


def _mode_map(modes: Dict[str, Dict[str, Any]], field: str, default: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for mode in _MODES:
        mode_cfg = dict(modes.get(mode, {}) or {})
        out[mode] = deepcopy(mode_cfg.get(field, default))
    return out


def _selected_profile_to_legacy(selected: Dict[str, Any]) -> Dict[str, Any]:
    """
    Expand a single selected scenario profile into legacy *by_mode maps so
    existing intel/planners remain compatible during migration.
    """
    src = dict(selected or {})
    if "bank_minerals" in src or "bank_gas" in src:
        raise RuntimeError("invalid_contract:build_profile:selected:deprecated_bank_fields")

    comp = deepcopy(src.get("comp", {}))
    priority = list(src.get("priority", []))
    pid = deepcopy(src.get("pid", {}))
    army_supply = deepcopy(src.get("army_supply_milestones", []))
    unit_counts = deepcopy(src.get("unit_count_milestones", []))
    timing = deepcopy(src.get("timing_attacks", []))
    prod_targets = deepcopy(src.get("production_structure_targets", {}))
    prod_scale = deepcopy(src.get("production_scale", {}))
    tech_structs = deepcopy(src.get("tech_structure_targets", {}))
    tech_timing = deepcopy(src.get("tech_timing_milestones", []))

    out: Dict[str, Any] = {}
    for mode in _MODES:
        out[f"comp_{mode.lower()}"] = deepcopy(comp)
        out[f"priority_{mode.lower()}"] = list(priority)
    out["pid_tuning_by_mode"] = {mode: deepcopy(pid) for mode in _MODES}
    out["army_supply_milestones_by_mode"] = {mode: deepcopy(army_supply) for mode in _MODES}
    out["unit_count_milestones_by_mode"] = {mode: deepcopy(unit_counts) for mode in _MODES}
    out["timing_attacks_by_mode"] = {mode: deepcopy(timing) for mode in _MODES}
    out["production_structure_targets_by_mode"] = {mode: deepcopy(prod_targets) for mode in _MODES}
    out["production_scale_by_mode"] = {mode: deepcopy(prod_scale) for mode in _MODES}
    out["tech_structure_targets_by_mode"] = {mode: deepcopy(tech_structs) for mode in _MODES}
    out["tech_timing_milestones_by_mode"] = {mode: deepcopy(tech_timing) for mode in _MODES}
    out["transition_overrides"] = deepcopy(src.get("transition_overrides", {}))
    out["scenario_overrides_by_phase"] = deepcopy(src.get("scenario_overrides_by_phase", {}))
    out["seed"] = deepcopy(src.get("seed", {}))
    return out


def expand_compact_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accept either:
    1) legacy flat format (already expanded), or
       2) compact format:
       {
         "modes": {
           "STANDARD": {
             "comp": {...},
             "priority": [...],
             "pid": {...},
             "army_supply_milestones": [...],
             "unit_count_milestones": [...],
             "timing_attacks": [...],
             "production_structure_targets": {...},
             "production_scale": {...},
             "tech_structure_targets": {...},
             "tech_timing_milestones": [...],
           },
           ...
         },
         "transition_overrides": {...},
         "scenario_overrides_by_phase": {
           "OPENING": {"AGGRESSIVE": {...}, "NORMAL": {...}, "GREEDY": {...}},
           "MIDGAME": {...},
           "LATEGAME": {...},
         }
       }
    """
    raw = deepcopy(dict(profile or {}))
    # New canonical contract: selected scenario profile.
    scenarios = raw.get("scenarios")
    if isinstance(scenarios, dict):
        # If caller passed a phase-level profile with all scenarios, caller must select one.
        # We keep strict behavior to avoid silent wrong picks.
        known = [k for k in scenarios.keys() if str(k).upper() in _SCENARIOS]
        if known:
            raise RuntimeError("invalid_contract:build_profile:scenarios_not_selected")
        return _selected_profile_to_legacy(raw)

    modes = raw.get("modes")
    if not isinstance(modes, dict):
        return _selected_profile_to_legacy(raw)

    out: Dict[str, Any] = {}
    for mode in _MODES:
        mode_cfg = dict(modes.get(mode, {}) or {})
        if "bank_minerals" in mode_cfg or "bank_gas" in mode_cfg:
            raise RuntimeError(f"invalid_contract:build_profile:{mode}:deprecated_bank_fields")
        out[f"comp_{mode.lower()}"] = deepcopy(mode_cfg.get("comp", {}))
        out[f"priority_{mode.lower()}"] = list(mode_cfg.get("priority", []))

    out["pid_tuning_by_mode"] = _mode_map(modes, "pid", {})
    out["army_supply_milestones_by_mode"] = _mode_map(modes, "army_supply_milestones", [])
    out["unit_count_milestones_by_mode"] = _mode_map(modes, "unit_count_milestones", [])
    out["timing_attacks_by_mode"] = _mode_map(modes, "timing_attacks", [])
    out["production_structure_targets_by_mode"] = _mode_map(modes, "production_structure_targets", {})
    out["production_scale_by_mode"] = _mode_map(modes, "production_scale", {})
    out["tech_structure_targets_by_mode"] = _mode_map(modes, "tech_structure_targets", {})
    out["tech_timing_milestones_by_mode"] = _mode_map(modes, "tech_timing_milestones", [])
    out["transition_overrides"] = deepcopy(raw.get("transition_overrides", {}))
    out["scenario_overrides_by_phase"] = deepcopy(raw.get("scenario_overrides_by_phase", {}))
    out["seed"] = deepcopy(raw.get("seed", {}))
    return out

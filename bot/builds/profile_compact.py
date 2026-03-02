from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


_MODES = ("DEFENSIVE", "STANDARD", "PUNISH", "RUSH_RESPONSE")


def _mode_map(modes: Dict[str, Dict[str, Any]], field: str, default: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for mode in _MODES:
        mode_cfg = dict(modes.get(mode, {}) or {})
        out[mode] = deepcopy(mode_cfg.get(field, default))
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
             "bank_minerals": 650,
             "bank_gas": 180,
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
         "reserve_costs": {...},
         "transition_overrides": {...}
       }
    """
    raw = deepcopy(dict(profile or {}))
    modes = raw.get("modes")
    if not isinstance(modes, dict):
        return raw

    out: Dict[str, Any] = {}
    for mode in _MODES:
        mode_cfg = dict(modes.get(mode, {}) or {})
        out[f"comp_{mode.lower()}"] = deepcopy(mode_cfg.get("comp", {}))
        out[f"priority_{mode.lower()}"] = list(mode_cfg.get("priority", []))

    out["reserve_costs"] = deepcopy(raw.get("reserve_costs", {}))
    out["bank_setpoint_minerals"] = _mode_map(modes, "bank_minerals", 650)
    out["bank_setpoint_gas"] = _mode_map(modes, "bank_gas", 180)
    out["pid_tuning_by_mode"] = _mode_map(modes, "pid", {})
    out["army_supply_milestones_by_mode"] = _mode_map(modes, "army_supply_milestones", [])
    out["unit_count_milestones_by_mode"] = _mode_map(modes, "unit_count_milestones", [])
    out["timing_attacks_by_mode"] = _mode_map(modes, "timing_attacks", [])
    out["production_structure_targets_by_mode"] = _mode_map(modes, "production_structure_targets", {})
    out["production_scale_by_mode"] = _mode_map(modes, "production_scale", {})
    out["tech_structure_targets_by_mode"] = _mode_map(modes, "tech_structure_targets", {})
    out["tech_timing_milestones_by_mode"] = _mode_map(modes, "tech_timing_milestones", [])
    out["transition_overrides"] = deepcopy(raw.get("transition_overrides", {}))
    return out


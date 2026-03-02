from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from bot.builds import PROFILES_BY_OPENING
from bot.builds.profile_compact import expand_compact_profile


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


def resolve_build_profile(*, opening_selected: str, transition_target: str) -> Dict[str, Any]:
    opening = str(opening_selected or "").strip()
    if not opening:
        raise RuntimeError("missing_contract:macro.opening.selected")
    if opening not in PROFILES_BY_OPENING:
        raise RuntimeError(f"missing_contract:build_profile:{opening}")

    profile = expand_compact_profile(deepcopy(PROFILES_BY_OPENING[opening]))
    if "bank_setpoint_minerals" in profile or "bank_setpoint_gas" in profile:
        raise RuntimeError(f"invalid_contract:build_profile:{opening}:deprecated_bank_fields")
    transition_overrides = dict(profile.pop("transition_overrides", {}) or {})
    transition = str(transition_target or "").strip().upper()
    if transition and transition in transition_overrides:
        profile = _deep_merge(profile, dict(transition_overrides[transition]))
    if "bank_setpoint_minerals" in profile or "bank_setpoint_gas" in profile:
        raise RuntimeError(f"invalid_contract:build_profile:{opening}:deprecated_bank_fields")

    missing = [k for k in _REQUIRED_KEYS if k not in profile]
    if missing:
        raise RuntimeError(f"invalid_contract:build_profile:{opening}:missing:{','.join(sorted(missing))}")

    return profile

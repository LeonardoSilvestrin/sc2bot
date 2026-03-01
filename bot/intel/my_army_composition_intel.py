# =============================================================================
# bot/intel/my_army_composition_intel.py  (NEW)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from bot.mind.awareness import Awareness, K
from bot.mind.attention import Attention


@dataclass(frozen=True)
class MyArmyCompositionConfig:
    """
    Strategy-level macro reference:
      - desired mode (discrete)
      - desired comp (ratios)
    This is NOT production/spending. It's the setpoint.

    Keep TTL short: consumers should treat it as "recent intent".
    """
    ttl_s: float = 25.0
    min_confidence: float = 0.55

    # Default comps (ratios sum ~= 1.0)
    comp_defensive: Dict[str, float] = None
    comp_standard: Dict[str, float] = None
    comp_punish: Dict[str, float] = None
    comp_rush_response: Dict[str, float] = None
    priority_defensive: List[str] = None
    priority_standard: List[str] = None
    priority_punish: List[str] = None
    priority_rush_response: List[str] = None
    reserve_costs: Dict[str, Tuple[int, int]] = None

    def __post_init__(self):
        object.__setattr__(
            self,
            "comp_defensive",
            self.comp_defensive
            or {
                "MARINE": 0.65,
                "MARAUDER": 0.15,
                "SIEGETANK": 0.15,
                "MEDIVAC": 0.05,
            },
        )
        object.__setattr__(
            self,
            "comp_standard",
            self.comp_standard
            or {
                "MARINE": 0.52,
                "MARAUDER": 0.20,
                "SIEGETANK": 0.13,
                "MEDIVAC": 0.15,
            },
        )
        object.__setattr__(
            self,
            "comp_punish",
            self.comp_punish
            or {
                "MARINE": 0.55,
                "MARAUDER": 0.12,
                "SIEGETANK": 0.13,
                "MEDIVAC": 0.20,
            },
        )
        object.__setattr__(
            self,
            "comp_rush_response",
            self.comp_rush_response
            or {
                "MARINE": 0.55,
                "MARAUDER": 0.18,
                "SIEGETANK": 0.22,
                "MEDIVAC": 0.05,
            },
        )
        object.__setattr__(self, "priority_defensive", self.priority_defensive or ["SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"])
        object.__setattr__(self, "priority_standard", self.priority_standard or ["SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"])
        object.__setattr__(self, "priority_punish", self.priority_punish or ["SIEGETANK", "MARINE", "MEDIVAC", "MARAUDER"])
        object.__setattr__(
            self, "priority_rush_response", self.priority_rush_response or ["SIEGETANK", "MARINE", "MARAUDER", "MEDIVAC"]
        )
        object.__setattr__(
            self,
            "reserve_costs",
            self.reserve_costs
            or {
                "SIEGETANK": (150, 125),
                "MARINE": (50, 0),
                "MARAUDER": (100, 25),
                "MEDIVAC": (100, 100),
                "REAPER": (50, 50),
                "HELLION": (100, 0),
                "BANSHEE": (150, 100),
            },
        )


def _normalize(comp: Dict[str, float]) -> Dict[str, float]:
    try:
        total = float(sum(float(v) for v in comp.values()))
    except Exception:
        return dict(comp)
    if total <= 0:
        return dict(comp)
    return {str(k): float(v) / total for k, v in comp.items()}


def _prepend_unique(items: List[str], head: str) -> List[str]:
    if not head:
        return list(items)
    out = [str(head)]
    for it in items:
        s = str(it)
        if s == str(head):
            continue
        out.append(s)
    return out


def _inject_unit_comp_bias(comp: Dict[str, float], *, unit_name: str, weight: float = 0.12) -> Dict[str, float]:
    out = dict(comp)
    if unit_name in out:
        return out
    out[str(unit_name)] = float(weight)
    return _normalize(out)


def _apply_opening_bias(
    *,
    comp: Dict[str, float],
    priority_units: List[str],
    opening_selected: str,
    transition_target: str,
    banshee_harass_done: bool,
) -> tuple[Dict[str, float], List[str]]:
    out_comp = dict(comp)
    out_prio = list(priority_units)
    wants_banshee_path = str(opening_selected) == "BansheeHellionOpen" or str(transition_target).upper() == "BANSHEE"
    if bool(wants_banshee_path) and not bool(banshee_harass_done):
        out_prio = _prepend_unique(out_prio, "BANSHEE")
        out_prio = _prepend_unique(out_prio, "HELLION")
        out_comp = _inject_unit_comp_bias(out_comp, unit_name="HELLION", weight=0.16)
        out_comp = _inject_unit_comp_bias(out_comp, unit_name="BANSHEE", weight=0.14)
    return _normalize(out_comp), out_prio


def _harass_missing_unit_from_cooldown(*, awareness: Awareness, now: float) -> str | None:
    """
    Looks at Ego cooldown rejection traces and returns the missing unit for the
    reaper-hellion harass proposal when available.
    """
    snap = awareness.mem.snapshot(now=now, prefix=K("ops", "cooldown"), max_age=90.0)
    latest_t = -1.0
    missing: str | None = None

    for sk, entry in snap.items():
        parts = sk.split(":")
        # Expected: ops:cooldown:<proposal_id>:reason
        if len(parts) < 4:
            continue
        if parts[0] != "ops" or parts[1] != "cooldown":
            continue
        if parts[-1] != "reason":
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
        if not unit:
            continue

        if t > latest_t:
            latest_t = t
            missing = unit

    return missing


def derive_my_army_composition_intel(
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    cfg: MyArmyCompositionConfig = MyArmyCompositionConfig(),
) -> None:
    """
    Reads enemy opening belief from Awareness, emits desired mode+comp into Awareness.

    Writes:
      - macro:desired:mode
      - macro:desired:comp
      - macro:desired:last_update_t
    """
    enemy_kind = awareness.mem.get(K("enemy", "opening", "kind"), now=now, default="NORMAL")
    conf = awareness.mem.get(K("enemy", "opening", "confidence"), now=now, default=0.0)
    rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
    opening_selected = str(awareness.mem.get(K("macro", "opening", "selected"), now=now, default="") or "")
    transition_target = str(awareness.mem.get(K("macro", "opening", "transition_target"), now=now, default="STIM") or "STIM").upper()
    banshee_harass_done = bool(awareness.mem.get(K("ops", "harass", "banshee", "done"), now=now, default=False))

    mode = "STANDARD"
    if rush_state in {"CONFIRMED", "HOLDING"}:
        mode = "RUSH_RESPONSE"
    elif float(conf) >= float(cfg.min_confidence):
        if str(enemy_kind) == "AGGRESSIVE":
            mode = "DEFENSIVE"
        elif str(enemy_kind) == "GREEDY":
            mode = "PUNISH"
        else:
            mode = "STANDARD"

    if mode == "RUSH_RESPONSE":
        comp = _normalize(dict(cfg.comp_rush_response))
        priority_units = list(cfg.priority_rush_response)
    elif mode == "DEFENSIVE":
        comp = _normalize(dict(cfg.comp_defensive))
        priority_units = list(cfg.priority_defensive)
    elif mode == "PUNISH":
        comp = _normalize(dict(cfg.comp_punish))
        priority_units = list(cfg.priority_punish)
    else:
        comp = _normalize(dict(cfg.comp_standard))
        priority_units = list(cfg.priority_standard)

    missing_harass_unit = _harass_missing_unit_from_cooldown(awareness=awareness, now=now)
    if missing_harass_unit is not None:
        priority_units = _prepend_unique(priority_units, missing_harass_unit)
        comp = _inject_unit_comp_bias(comp, unit_name=str(missing_harass_unit), weight=0.12)

    comp, priority_units = _apply_opening_bias(
        comp=comp,
        priority_units=priority_units,
        opening_selected=str(opening_selected),
        transition_target=str(transition_target),
        banshee_harass_done=bool(banshee_harass_done),
    )

    top_unit = str(priority_units[0]) if priority_units else ""
    reserve = cfg.reserve_costs.get(top_unit, (0, 0))
    reserve_m, reserve_g = int(reserve[0]), int(reserve[1])

    awareness.mem.set(K("macro", "desired", "mode"), value=str(mode), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "comp"), value=dict(comp), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "priority_units"), value=list(priority_units), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "reserve_unit"), value=str(top_unit), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "reserve_minerals"), value=int(reserve_m), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "reserve_gas"), value=int(reserve_g), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(
        K("macro", "desired", "signals"),
        value={
            "rush_state": str(rush_state),
            "enemy_kind": str(enemy_kind),
            "confidence": float(conf),
            "opening_selected": str(opening_selected),
            "transition_target": str(transition_target),
            "banshee_harass_done": bool(banshee_harass_done),
            "missing_harass_unit": str(missing_harass_unit or ""),
        },
        now=now,
        ttl=float(cfg.ttl_s),
    )
    awareness.mem.set(K("macro", "desired", "last_update_t"), value=float(now), now=now, ttl=None)

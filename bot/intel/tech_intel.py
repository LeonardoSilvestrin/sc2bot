from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sc2.ids.upgrade_id import UpgradeId as Up

from bot.intel.utils.upgrade_catalog import derive_upgrades_from_comp
from bot.mind.awareness import Awareness, K


@dataclass(frozen=True)
class TechIntelConfig:
    ttl_s: float = 25.0


def _upgrade_names_from_comp(*, comp: dict[str, float], reserve_unit: str) -> list[str]:
    return derive_upgrades_from_comp(comp=dict(comp), reserve_unit=str(reserve_unit))


def derive_tech_intel(
    *,
    awareness: Awareness,
    now: float,
    profile: dict[str, Any],
    mode: str,
    comp: dict[str, float],
    reserve_unit: str,
    cfg: TechIntelConfig = TechIntelConfig(),
) -> dict[str, Any]:
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
    opening_selected = str(
        awareness.mem.get(K("macro", "opening", "selected"), now=now, default="BansheeHellionOpen") or "BansheeHellionOpen"
    )
    if opening_selected == "BansheeHellionOpen":
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
    tech_targets = {"upgrades": list(upgrades), "structures": dict(tech_structure_targets)}
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
    awareness.mem.set(K("macro", "desired", "tech_structure_targets"), value=dict(tech_structure_targets), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "tech_timing_milestones"), value=list(tech_timing_milestones), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "tech_targets"), value=dict(tech_targets), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "construction_targets"), value=dict(construction_targets), now=now, ttl=float(cfg.ttl_s))
    return {
        "production_structure_targets": dict(production_structure_targets),
        "production_scale": dict(production_scale),
        "tech_structure_targets": dict(tech_structure_targets),
        "tech_timing_milestones": list(tech_timing_milestones),
        "upgrades": list(upgrades),
    }

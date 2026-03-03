from __future__ import annotations

from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.ids.upgrade_id import UpgradeId as Up

# Candidate upgrades by unit role. Invalid/unavailable upgrades for a given
# Ares/python-sc2 version are filtered automatically at runtime.
UNIT_UPGRADE_CANDIDATES: dict[str, list[str]] = {
    "BANSHEE": ["BANSHEECLOAK", "BANSHEESPEED"],
    "CYCLONE": ["MAGFIELDLAUNCHERS", "DRILLCLAWS", "SMARTSERVOS"],
    "HELLION": ["INFERNALPREIGNITERS", "SMARTSERVOS"],
    "WIDOWMINE": ["DRILLCLAWS"],
    "SIEGETANK": ["SMARTSERVOS"],
    "THOR": ["SMARTSERVOS"],
    "LIBERATOR": ["TERRANSHIPWEAPONSLEVEL1"],
    "VIKINGFIGHTER": ["TERRANSHIPWEAPONSLEVEL1"],
    "MEDIVAC": ["TERRANSHIPWEAPONSLEVEL1"],
    "MARINE": ["STIMPACK", "SHIELDWALL", "PUNISHERGRENADES"],
    "MARAUDER": ["STIMPACK", "SHIELDWALL", "PUNISHERGRENADES"],
    "GHOST": ["PERSONALCLOAKING"],
}

GLOBAL_FALLBACK_UPGRADES: list[str] = [
    "BANSHEECLOAK",
    "DRILLCLAWS",
    "SMARTSERVOS",
    "TERRANVEHICLEWEAPONSLEVEL1",
    "TERRANVEHICLEANDSHIPARMORSLEVEL1",
    "TERRANSHIPWEAPONSLEVEL1",
]


def researchable_upgrade_names() -> set[str]:
    out: set[str] = set()
    for up in Up:
        researched_from = UPGRADE_RESEARCHED_FROM.get(up, None)
        if researched_from is None:
            continue
        if researched_from not in RESEARCH_INFO:
            continue
        if up not in RESEARCH_INFO[researched_from]:
            continue
        out.add(str(up.name))
    return out


def derive_upgrades_from_comp(*, comp: dict[str, float], reserve_unit: str) -> list[str]:
    valid = researchable_upgrade_names()
    ordered_units = sorted(
        [(str(name), float(weight)) for name, weight in dict(comp or {}).items()],
        key=lambda x: x[1],
        reverse=True,
    )
    banshee_pressure = float(comp.get("BANSHEE", 0.0) or 0.0) >= 0.12 or str(reserve_unit) == "BANSHEE"

    desired: list[str] = []
    if banshee_pressure:
        desired.append("BANSHEECLOAK")
    for unit_name, weight in ordered_units:
        if float(weight) <= 0.0:
            continue
        desired.extend(list(UNIT_UPGRADE_CANDIDATES.get(str(unit_name), [])))
    desired.extend(list(GLOBAL_FALLBACK_UPGRADES))

    seen: set[str] = set()
    out: list[str] = []
    for name in desired:
        n = str(name)
        if n in seen:
            continue
        seen.add(n)
        if n in valid:
            out.append(n)
    return out


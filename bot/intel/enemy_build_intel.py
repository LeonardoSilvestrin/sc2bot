# bot/intel/enemy_build_intel.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.mind.awareness import Awareness, K
from bot.mind.attention import Attention


@dataclass(frozen=True)
class EnemyBuildIntelConfig:
    """
    MVP heuristic config.
    You can tune later without changing contract.
    """
    ttl_s: float = 12.0

    # timing thresholds
    early_s: float = 210.0     # ~3:30 window for "early aggression" classification
    greedy_s: float = 165.0    # ~2:45 window for "fast expand" classification

    # aggression signals
    rush_units_near_bases: int = 6
    rush_confidence_min: float = 0.65


def _count_enemy_bases(enemy_structures: Dict[U, int]) -> int:
    # Townhalls by race (visible only)
    return int(
        enemy_structures.get(U.HATCHERY, 0)
        + enemy_structures.get(U.LAIR, 0)
        + enemy_structures.get(U.HIVE, 0)
        + enemy_structures.get(U.NEXUS, 0)
        + enemy_structures.get(U.COMMANDCENTER, 0)
        + enemy_structures.get(U.ORBITALCOMMAND, 0)
        + enemy_structures.get(U.PLANETARYFORTRESS, 0)
    )


def _sum_units(enemy_units: Dict[U, int], types: Tuple[U, ...]) -> int:
    return int(sum(int(enemy_units.get(t, 0)) for t in types))


def derive_enemy_build_intel(
    bot,
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    cfg: EnemyBuildIntelConfig = EnemyBuildIntelConfig(),
) -> None:
    """
    EnemyBuildIntel (inference -> Awareness):
      - reads Attention.enemy_build (tick facts)
      - infers enemy opening: GREEDY / NORMAL / AGGRESSIVE
      - writes to Awareness with TTL (belief/state, not tick fact)

    Rule: may write to Awareness; must not issue commands.
    """
    eb = attention.enemy_build
    enemy_units: Dict[U, int] = eb.enemy_units
    enemy_structs: Dict[U, int] = eb.enemy_structures

    enemy_bases = _count_enemy_bases(enemy_structs)

    # Signals we can use right now (MVP)
    near_bases = int(attention.combat.enemy_count_near_bases)
    threatened = bool(attention.combat.threatened)

    lings = _sum_units(enemy_units, (U.ZERGLING,))
    marines = _sum_units(enemy_units, (U.MARINE,))
    reapers = _sum_units(enemy_units, (U.REAPER,))
    zealots = _sum_units(enemy_units, (U.ZEALOT,))
    adepts = _sum_units(enemy_units, (U.ADEPT,))
    stalkers = _sum_units(enemy_units, (U.STALKER,))

    early = float(now) <= float(cfg.early_s)
    greedy_window = float(now) <= float(cfg.greedy_s)

    kind = "NORMAL"
    conf = 0.40

    # Natural visibility signal (new, from sensor)
    nat_on_ground = bool(getattr(eb, "enemy_natural_on_ground", False))

    # 1) Aggressive/Rush: strong immediate combat signals near our bases early.
    if early and (near_bases >= int(cfg.rush_units_near_bases) or (threatened and near_bases >= 3)):
        kind = "AGGRESSIVE"
        conf = min(0.95, 0.55 + 0.05 * float(near_bases))
        if (lings + marines + reapers + zealots + adepts + stalkers) >= 6:
            conf = min(0.98, conf + 0.10)

    # 2) Greedy: visible fast 2nd base in a greedy timing window and not much pressure.
    # Upgraded: use natural townhall visibility if we have it.
    elif greedy_window and (nat_on_ground or enemy_bases >= 2) and near_bases <= 1 and not threatened:
        kind = "GREEDY"
        conf = 0.75

    # else NORMAL

    # First-time "we saw anything meaningful" marker (permanent).
    # This is useful for planners that want to react on first scout info.
    first_seen = awareness.mem.get(K("enemy", "opening", "first_seen_t"), now=now, default=None)
    saw_anything = (len(enemy_units) > 0) or (len(enemy_structs) > 0)
    if first_seen is None and saw_anything:
        awareness.mem.set(K("enemy", "opening", "first_seen_t"), value=float(now), now=now, ttl=None)

    signals = {
        "t": round(float(now), 2),
        "early": bool(early),
        "greedy_window": bool(greedy_window),
        "enemy_bases_visible": int(enemy_bases),
        "enemy_near_our_bases": int(near_bases),
        "threatened": bool(threatened),
        "natural_on_ground": bool(nat_on_ground),
        "natural_townhall_progress": float(getattr(eb, "enemy_natural_townhall_progress", 0.0) or 0.0),
        "natural_townhall_type": str(getattr(eb, "enemy_natural_townhall_type", None)),
        "seen_units": {
            "lings": int(lings),
            "marines": int(marines),
            "reapers": int(reapers),
            "zealots": int(zealots),
            "adepts": int(adepts),
            "stalkers": int(stalkers),
        },
        # New sensor payload for debugging + future heuristics:
        "main_units": dict(getattr(eb, "enemy_units_main", {}) or {}),
        "main_structures": dict(getattr(eb, "enemy_structures_main", {}) or {}),
        "structures_progress": dict(getattr(eb, "enemy_structures_progress", {}) or {}),
    }

    awareness.mem.set(K("enemy", "opening", "kind"), value=str(kind), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "opening", "confidence"), value=float(conf), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "opening", "signals"), value=signals, now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "opening", "last_update_t"), value=float(now), now=now, ttl=None)
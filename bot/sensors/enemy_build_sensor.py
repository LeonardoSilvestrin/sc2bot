# bot/sensors/enemy_build_sensor.py
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.mind.attention import EnemyBuildSnapshot


_TOWNHALL_TYPES: Tuple[U, ...] = (
    U.HATCHERY,
    U.LAIR,
    U.HIVE,
    U.NEXUS,
    U.COMMANDCENTER,
    U.ORBITALCOMMAND,
    U.PLANETARYFORTRESS,
)


def _enemy_main_strict(bot) -> Point2:
    locs = getattr(bot, "enemy_start_locations", None)
    if not locs or len(locs) == 0:
        raise RuntimeError("EnemyBuildSensor requires bot.enemy_start_locations[0]")
    return locs[0]


def _enemy_natural_from_expansions(bot, enemy_main: Point2) -> Optional[Point2]:
    exps = getattr(bot, "expansion_locations_list", None)
    if not exps or len(exps) < 2:
        return None
    # nearest to enemy main is usually the main expansion; second nearest is natural
    ordered = sorted(exps, key=lambda p: p.distance_to(enemy_main))
    return ordered[1] if len(ordered) >= 2 else None


def _progress_stats(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "ready": 0, "incomplete": 0, "min": 0.0, "max": 0.0, "avg": 0.0}
    c = len(values)
    ready = sum(1 for v in values if v >= 0.999)
    incomplete = c - ready
    mn = min(values)
    mx = max(values)
    avg = sum(values) / float(c)
    return {
        "count": int(c),
        "ready": int(ready),
        "incomplete": int(incomplete),
        "min": float(round(mn, 4)),
        "max": float(round(mx, 4)),
        "avg": float(round(avg, 4)),
    }


def derive_enemy_build_sensor(bot) -> EnemyBuildSnapshot:
    """
    EnemyBuildSensor (tick facts -> Attention):
      - counts enemy UNITS and STRUCTURES we currently see this tick
      - also extracts "what's in enemy main" and structure build_progress stats
      - detects whether enemy natural townhall is on the ground (visible)

    Rule: no side-effects. Strict positioning sources (no fallbacks).
    """
    enemy_main = _enemy_main_strict(bot)
    enemy_nat = _enemy_natural_from_expansions(bot, enemy_main)

    # radii are deliberately "loose" so we don't miss mineral line / tech placements
    main_radius = 26.0
    natural_radius = 10.0

    units_all = Counter()
    structs_all = Counter()
    units_main = Counter()
    structs_main = Counter()

    progress_by_type: Dict[U, list[float]] = defaultdict(list)

    # enemy units currently visible
    for u in bot.enemy_units:
        try:
            tid = u.type_id
            units_all[tid] += 1
            if u.position.distance_to(enemy_main) <= main_radius:
                units_main[tid] += 1
        except Exception:
            continue

    # enemy structures currently visible (+ progress stats)
    for s in bot.enemy_structures:
        try:
            tid = s.type_id
            structs_all[tid] += 1

            # build_progress is meaningful for "ongoing vs ready"
            prog = float(getattr(s, "build_progress", 1.0))
            # clamp for sanity
            if prog < 0.0:
                prog = 0.0
            if prog > 1.0:
                prog = 1.0
            progress_by_type[tid].append(prog)

            if s.position.distance_to(enemy_main) <= main_radius:
                structs_main[tid] += 1
        except Exception:
            continue

    # natural townhall visibility
    natural_on_ground = False
    nat_best_prog: Optional[float] = None
    nat_best_type: Optional[U] = None
    if enemy_nat is not None:
        for s in bot.enemy_structures:
            try:
                if s.type_id not in _TOWNHALL_TYPES:
                    continue
                if s.position.distance_to(enemy_nat) <= natural_radius:
                    natural_on_ground = True
                    prog = float(getattr(s, "build_progress", 1.0))
                    if nat_best_prog is None or prog > nat_best_prog:
                        nat_best_prog = prog
                        nat_best_type = s.type_id
            except Exception:
                continue

    progress_stats = {tid: _progress_stats(vals) for tid, vals in progress_by_type.items()}

    return EnemyBuildSnapshot(
        enemy_units=dict(units_all),
        enemy_structures=dict(structs_all),
        enemy_main_pos=enemy_main,
        enemy_natural_pos=enemy_nat,
        enemy_units_main=dict(units_main),
        enemy_structures_main=dict(structs_main),
        enemy_structures_progress=progress_stats,
        enemy_natural_on_ground=bool(natural_on_ground),
        enemy_natural_townhall_progress=float(nat_best_prog) if nat_best_prog is not None else None,
        enemy_natural_townhall_type=nat_best_type,
    )
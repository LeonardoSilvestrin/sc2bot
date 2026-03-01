from __future__ import annotations

from typing import Dict, Tuple

from sc2.ids.unit_typeid import UnitTypeId as U


_TOWNHALL_TYPES: Tuple[U, ...] = (
    U.HATCHERY,
    U.LAIR,
    U.HIVE,
    U.NEXUS,
    U.COMMANDCENTER,
    U.ORBITALCOMMAND,
    U.PLANETARYFORTRESS,
)


def sum_units(units: Dict[U, int], types: Tuple[U, ...]) -> int:
    return int(sum(int(units.get(t, 0)) for t in types))


def count_enemy_bases(enemy_structures: Dict[U, int]) -> int:
    return int(sum(int(enemy_structures.get(t, 0)) for t in _TOWNHALL_TYPES))


def expected_workers(now: float, *, period_s: float, cap: int = 80) -> int:
    out = 12 + int(max(0.0, float(now)) // max(1.0, float(period_s)))
    return int(max(12, min(int(cap), out)))

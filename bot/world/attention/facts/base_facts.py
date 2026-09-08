from __future__ import annotations

from dataclasses import dataclass

from ares.consts import TOWNHALL_TYPES as _ARES_TOWNHALL_TYPES
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from .unit_facts import UnitSnapshot

# Sourced from Ares so relocating Terran townhalls remain represented.
TOWNHALL_TYPES: frozenset[UnitTypeId] = frozenset(_ARES_TOWNHALL_TYPES)


@dataclass(frozen=True, slots=True)
class BaseSnapshot:
    """One currently held base, without threat or protection judgements."""

    base_id: str
    position: Point2
    is_main: bool
    townhall: UnitSnapshot | None = None

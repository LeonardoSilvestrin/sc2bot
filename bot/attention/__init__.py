"""ATTENTION: perception, before any interpretation.

Two readings of the game. The static map is read once, in ``on_start``:
`read_map` returns a frozen `MapView` with its `MapTopology` -- regions,
passages, expansions and adjacency. The frame is read every step: `observe`
returns an immutable `AttentionState`. Neither says who controls a place or
how dangerous it is; that is Awareness.
"""

from .frame import (
    MARINE_POWER,
    WORKER_TYPES,
    AttentionState,
    BaseView,
    UnitView,
    is_army,
    observe,
    unit_power,
    unit_view,
)
from .map import MapView, as_point, pathable_lattice, read_map
from .topology import MapPassage, MapRegion, MapTopology

__all__ = [
    "MARINE_POWER",
    "WORKER_TYPES",
    "AttentionState",
    "BaseView",
    "MapPassage",
    "MapRegion",
    "MapTopology",
    "MapView",
    "UnitView",
    "as_point",
    "is_army",
    "observe",
    "pathable_lattice",
    "read_map",
    "unit_power",
    "unit_view",
]

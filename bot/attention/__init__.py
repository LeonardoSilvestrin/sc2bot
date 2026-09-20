"""ATTENTION: perception, before any interpretation.

Two readings of the game. The static map is read once, in ``on_start``:
`read_map` returns a frozen `MapView` with its `MapTopology` -- regions,
passages, expansions and adjacency. The frame is read every step: `observe`
returns an immutable `AttentionState`. Neither says who controls a place or
how dangerous it is; that is Awareness.

One record outlives the frame: `opening.OpeningObservations`, what the early
game showed of the enemy's opening and when it showed it. It is still
perception -- a fact that was observed stays a fact -- and what it means is
read in Awareness.
"""

from .frame import (
    MARINE_POWER,
    SPLASH_TARGETS,
    TERRAN_PRODUCTION,
    TERRAN_TRAINABLE,
    WORKER_TYPES,
    AttentionState,
    BaseView,
    UnitView,
    is_army,
    observe,
    unit_power,
    unit_view,
)
from .map import (
    BASE_SNAP_DISTANCE,
    EXPANSION_GAP,
    MapView,
    as_point,
    pathable_lattice,
    read_map,
)
from .opening import (
    GAS_STRUCTURES,
    OPENING_WINDOW,
    TOWNHALLS,
    ExpansionObservation,
    ExpansionStatus,
    OpeningObservations,
    OpeningWatch,
    StructureObservation,
)
from .topology import MapPassage, MapRegion, MapTopology

__all__ = [
    "BASE_SNAP_DISTANCE",
    "EXPANSION_GAP",
    "GAS_STRUCTURES",
    "MARINE_POWER",
    "OPENING_WINDOW",
    "SPLASH_TARGETS",
    "TERRAN_PRODUCTION",
    "TERRAN_TRAINABLE",
    "TOWNHALLS",
    "WORKER_TYPES",
    "AttentionState",
    "BaseView",
    "ExpansionObservation",
    "ExpansionStatus",
    "MapPassage",
    "MapRegion",
    "MapTopology",
    "MapView",
    "OpeningObservations",
    "OpeningWatch",
    "StructureObservation",
    "UnitView",
    "as_point",
    "is_army",
    "observe",
    "pathable_lattice",
    "read_map",
    "unit_power",
    "unit_view",
]

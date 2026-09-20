"""ATTENTION: perception, before any interpretation.

Two readings of the game. The static map is read once, in ``on_start``:
`read_map` returns a frozen `MapView` with its `MapTopology` -- regions,
passages, expansions and adjacency. The frame is read every step: `observe`
returns an immutable `AttentionState`. Neither says who controls a place or
how dangerous it is; that is Awareness.

Two records outlive the frame. `opening.OpeningObservations` is what the early
game showed of the enemy's opening and when it showed it; it is still
perception -- a fact that was observed stays a fact -- and what it means is
read in Awareness. `passages.PassageWatch` is the other: mineral walls and
rocks fall during a game, and it turns the neutral objects the game still
lists into the one thing about the map that moves, `MapPassage.state`. The
map's identity does not move with it.
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
    read_blockers,
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
from .passages import PassageChange, PassageWatch, passage_states
from .topology import (
    CLOSED,
    OPEN,
    UNKNOWN,
    MapBlocker,
    MapPassage,
    MapRegion,
    MapTopology,
    Passage,
    PassageState,
)

__all__ = [
    "BASE_SNAP_DISTANCE",
    "CLOSED",
    "EXPANSION_GAP",
    "GAS_STRUCTURES",
    "MARINE_POWER",
    "OPEN",
    "OPENING_WINDOW",
    "SPLASH_TARGETS",
    "TERRAN_PRODUCTION",
    "TERRAN_TRAINABLE",
    "TOWNHALLS",
    "UNKNOWN",
    "WORKER_TYPES",
    "AttentionState",
    "BaseView",
    "ExpansionObservation",
    "ExpansionStatus",
    "MapBlocker",
    "MapPassage",
    "MapRegion",
    "MapTopology",
    "MapView",
    "OpeningObservations",
    "OpeningWatch",
    "Passage",
    "PassageChange",
    "PassageState",
    "PassageWatch",
    "StructureObservation",
    "UnitView",
    "as_point",
    "is_army",
    "observe",
    "passage_states",
    "pathable_lattice",
    "read_blockers",
    "read_map",
    "unit_power",
    "unit_view",
]

"""MapControl holds the free army and governs noncombat map operations.

`policies.staging` chooses its anchor; `missions.remove_creep` coordinates
an early detector and a small escort against Zerg.
"""

from .missions.remove_creep import RemoveCreepConfig
from .planner import (
    MAP_CONTROL_PRIORITY,
    OWNER,
    MapControlConfig,
    MapControlPlan,
    MapControlPlanner,
)
from .policies.staging import StagingPlan, StagingPoint

__all__ = [
    "MAP_CONTROL_PRIORITY",
    "OWNER",
    "MapControlConfig",
    "MapControlPlan",
    "MapControlPlanner",
    "RemoveCreepConfig",
    "StagingPlan",
    "StagingPoint",
]

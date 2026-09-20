"""Intel owns every decision whose purpose is obtaining usable information.

- `planner.IntelPlanner`: the planner. Opens and ends the early scout, orders
  the proxy search Awareness' opening read asks for, and joins every Intel
  decision into one `IntelPlan`.
- `missions.early_scout.EarlyScoutMission`: one SCV reading the enemy opening.
- `policies.detection`: where to scan, the scan reserve, Missile Turrets.
- `policies.proxy`: where a proxy would be, on our half of the map.
- `policies.sensor_towers`: the Sensor Towers the radar barrier still misses.
"""

from .missions.early_scout import (
    ARRIVAL,
    KIND,
    OWNER,
    PHASE_PRIORITY,
    PROPOSAL_ID,
    READ_ENOUGH,
    SCOUT_TYPES,
    EarlyScoutMission,
    ScoutPhase,
    ScoutWindow,
)
from .planner import (
    LAP_SECTORS,
    PROXY_CONFIDENCE_AT,
    PROXY_SEARCH_AT,
    SCOUT_AT_WORKERS,
    START_BY,
    IntelPlanner,
    enemy_exits,
    scout_window,
    scouting_route,
)
from .policies.detection import Detection, DetectionConfig
from .policies.proxy import PROXY_LIMIT, proxy_route

__all__ = [
    "ARRIVAL",
    "Detection",
    "DetectionConfig",
    "EarlyScoutMission",
    "IntelPlanner",
    "KIND",
    "LAP_SECTORS",
    "OWNER",
    "PHASE_PRIORITY",
    "PROPOSAL_ID",
    "PROXY_CONFIDENCE_AT",
    "PROXY_LIMIT",
    "PROXY_SEARCH_AT",
    "READ_ENOUGH",
    "SCOUT_AT_WORKERS",
    "SCOUT_TYPES",
    "START_BY",
    "ScoutPhase",
    "ScoutWindow",
    "enemy_exits",
    "proxy_route",
    "scout_window",
    "scouting_route",
]

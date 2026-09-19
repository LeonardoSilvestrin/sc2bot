"""Intel owns every decision whose purpose is obtaining usable information.

- `planner.IntelPlanner`: the planner. Opens and ends the scout, and joins
  every Intel decision into one `IntelPlan`.
- `missions.scout.ScoutMission`: one SCV lapping the enemy main.
- `policies.detection`: where to scan, the scan reserve, Missile Turrets.
- `policies.sensor_towers`: the Sensor Towers the radar barrier still misses.
"""

from .missions.scout import KIND, LAP_TIMEOUT, OWNER, PROPOSAL_ID, SCOUT_TYPES, ScoutMission
from .planner import LAP_SECTORS, SCOUT_AT_WORKERS, START_BY, IntelPlanner, scouting_route
from .policies.detection import Detection, DetectionConfig

__all__ = [
    "Detection",
    "DetectionConfig",
    "IntelPlanner",
    "KIND",
    "LAP_SECTORS",
    "LAP_TIMEOUT",
    "OWNER",
    "PROPOSAL_ID",
    "SCOUT_AT_WORKERS",
    "SCOUT_TYPES",
    "START_BY",
    "ScoutMission",
    "scouting_route",
]

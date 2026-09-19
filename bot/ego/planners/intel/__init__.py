"""Intel owns every decision whose purpose is obtaining usable information."""

from .detection import Detection, DetectionConfig
from .missions.scout import KIND, LAP_TIMEOUT, OWNER, PROPOSAL_ID, SCOUT_TYPES, ScoutMission
from .planner import LAP_SECTORS, SCOUT_AT_WORKERS, START_BY, IntelPlanner, scouting_route

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

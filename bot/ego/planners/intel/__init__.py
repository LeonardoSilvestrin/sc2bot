"""Intel: one SCV looks at the enemy main early in the game.

- `planner.IntelPlanner`: whether a scout opens, is replaced or is cancelled
  before it sets out; the route and what of it was seen.
- `missions.scout.ScoutMission`: one scout on the route, and why it ends.
"""

from .missions.scout import KIND, LAP_TIMEOUT, OWNER, PROPOSAL_ID, SCOUT_TYPES, ScoutMission
from .planner import LAP_SECTORS, SCOUT_AT_WORKERS, START_BY, IntelPlanner, scouting_route

__all__ = [
    "KIND",
    "LAP_SECTORS",
    "LAP_TIMEOUT",
    "OWNER",
    "PROPOSAL_ID",
    "SCOUT_AT_WORKERS",
    "SCOUT_TYPES",
    "START_BY",
    "IntelPlanner",
    "ScoutMission",
    "scouting_route",
]

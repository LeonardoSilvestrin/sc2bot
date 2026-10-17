"""Defense: every threat incident is answered, with one budget, a rush is
held behind a Bunker, and a Changeling at home is shot.

- `planner.DefensePlanner`: one mission per incident, open while the incident
  is, and one rush defense while the rush reading says so.
- `missions.defend_area.DefendAreaMission`: the incident's budget, split into
  an air and a ground proposal.
- `missions.rush_defense.RushDefenseMission`: a Bunker at the base the rush
  hits, filled with Marines and repaired by SCVs.
- `policies.rush`: the rush reading, and where the Bunker goes.
- `policies.changelings`: one unit after each Changeling at home.
"""

from .missions.defend_area import COVER_MARGIN, KIND, OWNER, DefendAreaMission
from .missions.rush_defense import RushDefenseMission
from .planner import DefensePlanner
from .policies.rush import RushConfig, RushReading

__all__ = [
    "COVER_MARGIN",
    "KIND",
    "OWNER",
    "DefendAreaMission",
    "DefensePlanner",
    "RushConfig",
    "RushDefenseMission",
    "RushReading",
]

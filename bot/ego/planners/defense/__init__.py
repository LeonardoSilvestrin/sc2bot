"""Defense: every threat incident is answered, with one budget.

- `planner.DefensePlanner`: one mission per incident, open while the incident is.
- `missions.defend_area.DefendAreaMission`: the incident's budget, split into
  an air and a ground proposal.
"""

from .missions.defend_area import COVER_MARGIN, KIND, OWNER, DefendAreaMission
from .planner import DefensePlanner

__all__ = ["COVER_MARGIN", "KIND", "OWNER", "DefendAreaMission", "DefensePlanner"]

"""CoreArmy: the fallback owner of every army unit no one else needs. No
operation of its own, so no missions: `planner.plan` proposes directly."""

from .planner import FALLBACK_PRIORITY, OWNER, plan

__all__ = ["FALLBACK_PRIORITY", "OWNER", "plan"]

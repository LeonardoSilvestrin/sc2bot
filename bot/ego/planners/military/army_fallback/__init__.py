"""ArmyFallback: every army unit no one else needs, held at the rally.
No operation of its own, so no missions: `planner.ArmyFallbackPlanner`
proposes directly."""

from .planner import FALLBACK_PRIORITY, OWNER, ArmyFallbackPlanner

__all__ = ["FALLBACK_PRIORITY", "OWNER", "ArmyFallbackPlanner"]

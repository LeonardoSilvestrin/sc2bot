"""The default behavior: where combat units live when nothing else needs them.

    assessment.py   what we hold, what threatens it, and our combat posture
    planner.py      the anchor, how much of the army holds it, at what priority
    executor.py     keeping the core army on that anchor
    model.py        the posture/assessment/plan types all three share

Every combat unit a special mission has not claimed should be owned here,
so that ownership is always singular: a raid or a defense takes units *from*
this behavior through `MissionController`, and they come back to it when
that mission ends.
"""

from .assessment import StandingAssessor, derive_combat_posture
from .executor import StandingExecutor
from .model import (
    CombatPosture,
    StandingAssessment,
    StandingConfig,
    StandingPlan,
)
from .planner import StandingPlanner

__all__ = [
    "CombatPosture",
    "StandingAssessment",
    "StandingAssessor",
    "StandingConfig",
    "StandingExecutor",
    "StandingPlan",
    "StandingPlanner",
    "derive_combat_posture",
]

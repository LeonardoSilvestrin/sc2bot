"""Per-base defense, end to end.

    assessment.py   which bases are threatened, and by air or by ground
    planner.py      one proposal per threatened base, sized to the gap and
                    preferring the defenders that attack makes worth pulling
    executor.py     each defender in its role (SIEGE_ANCHOR or SCREEN) until
                    the base is clear, Tanks unsieged before release
    model.py        the config/assessment/plan/role types all three share
"""

from .assessment import DefenseAssessor
from .executor import DefendBaseExecutor
from .model import (
    DefenseAnchors,
    DefenseAssessment,
    DefenseConfig,
    DefensePlan,
    DefenseRole,
    SiegePhase,
    ThreatenedBase,
)
from .planner import DefensePlanner

__all__ = [
    "DefendBaseExecutor",
    "DefenseAnchors",
    "DefenseAssessment",
    "DefenseAssessor",
    "DefenseConfig",
    "DefensePlan",
    "DefensePlanner",
    "DefenseRole",
    "SiegePhase",
    "ThreatenedBase",
]

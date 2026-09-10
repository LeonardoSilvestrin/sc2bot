"""The economic track: what to spend on, not who to command.

Deliberately *not* shaped like the other behavior folders. Macro produces
`EconomicProposal`s admitted by `bot/engine/economy` against a virtual bank;
it never claims a unit, never holds a mission, and has no executor -- the
`AresEconomyCommands` adapter dispatches what the controller admits. Giving
it `assessment.py`/`planner.py`/`executor.py` would be a costume, not a
structure, so the mission-behavior contract in `bot/behavior/contracts.py`
does not apply here.

Its own split is by spend domain instead: `planner/` holds one proposal
builder per concern (workers, supply, gas, production, add-ons, expansion,
army), with `army_demand.py` playing the assessment role and
`macro_planner.py` composing them.
"""

from .macro_config import MacroPlannerConfig, ResourceOverflowConfig
from .macro_goals import ArmyUnitGoal, MacroGoalSet, ProductionGoal, UpgradeGoal
from .opening_macro_profiles import MACRO_PROFILES, macro_config_for_opening
from .planner import MacroPlanner
from .reference_build import (
    ReferenceBuild,
    ReferenceBuildPoint,
    bio_three_one_one_reference,
)
from .strategy_goal_profiles import banshee_cloak, bio_three_one_one

__all__ = [
    "MACRO_PROFILES",
    "ArmyUnitGoal",
    "MacroGoalSet",
    "MacroPlanner",
    "MacroPlannerConfig",
    "ProductionGoal",
    "ReferenceBuild",
    "ReferenceBuildPoint",
    "ResourceOverflowConfig",
    "UpgradeGoal",
    "banshee_cloak",
    "bio_three_one_one",
    "bio_three_one_one_reference",
    "macro_config_for_opening",
]

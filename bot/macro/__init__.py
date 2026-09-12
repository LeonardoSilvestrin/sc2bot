"""Macro: what the bot spends on, never who it commands.

`bot.behavior` governs units already on the map -- missions, squads, unit
leases -- arbitrated by `bot.engine.missions`. Macro governs a different
resource: minerals, gas, supply, production capacity, tech and timing,
arbitrated by `bot.engine.economy`. Both read the same Attention and
Awareness; neither imports the other.

    behavior -> MissionProposal  -> MissionController -> units
    macro    -> EconomicProposal -> EconomyController -> minerals, gas,
                                                         supply, production

Split by what a proposal buys, so the intelligence for one kind of spend
stays in one folder:

    builds/         one vertical folder per build: army composition,
                    production milestones, add-ons and upgrades
    composition/    shared doctrine vocabulary (core / support / specialized)
    strategy/       shared goal/config vocabulary and reference timings
    production/     units to train: the army's supply debt, workers
    construction/   structures to build: production capacity, add-ons,
                    supply, refineries
    expansion/      bases to take
    planner.py      MacroPlanner, composing those into one tick's proposals
    diagnostics.py  why it is or is not spending, once the controller ran
    contracts.py    SpendPlanner, the contract `planner.py` keeps

There is no `tech/` yet: `UpgradeGoal`, `upgrade_priority` and
`RESEARCH_UPGRADE` exist as vocabulary, but nothing proposes research. The
first upgrade proposer is where that folder starts.

Macro claims no unit and holds no mission. The SCV that lays a structure is
picked by the economy adapter while it executes a funded action -- an
operational need of construction, not a unit lease, and the seam where a
worker controller would later mediate.
"""

from .builds import banshee_cloak, battle_mech, bio_three_one_one
from .composition import BIO, MECH, CompositionDoctrine
from .contracts import SpendPlanner
from .diagnostics import MacroDiagnostics
from .planner import MacroPlanner, MacroStatus
from .strategy.config import MacroPlannerConfig, ResourceOverflowConfig
from .strategy.goals import ArmyUnitGoal, MacroGoalSet, ProductionGoal, UpgradeGoal
from .strategy.openings import MACRO_PROFILES, macro_config_for_opening
from .strategy.reference_build import (
    ReferenceBuild,
    ReferenceBuildPoint,
    bio_three_one_one_reference,
)

__all__ = [
    "BIO",
    "MACRO_PROFILES",
    "MECH",
    "ArmyUnitGoal",
    "CompositionDoctrine",
    "MacroDiagnostics",
    "MacroGoalSet",
    "MacroPlanner",
    "MacroPlannerConfig",
    "MacroStatus",
    "ProductionGoal",
    "ReferenceBuild",
    "ReferenceBuildPoint",
    "ResourceOverflowConfig",
    "SpendPlanner",
    "UpgradeGoal",
    "banshee_cloak",
    "battle_mech",
    "bio_three_one_one",
    "bio_three_one_one_reference",
    "macro_config_for_opening",
]

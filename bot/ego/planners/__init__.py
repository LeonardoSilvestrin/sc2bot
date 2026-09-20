"""Domain decisions expressed as plans and unit proposals.

Each subpackage is one domain with one planner: offense, defense, map control,
intel, economy and structure control. The planner owns the domain, a mission
(`missions/`) owns an operation, a policy (`policies/`) implements a decision
rule and knowledge (`knowledge/`) holds static domain facts; see
docs/architecture.md.
"""

from .contracts import (
    Command,
    CompositionPlan,
    CounterAdaptation,
    DetectionPlan,
    Domain,
    EarlyScoutReport,
    EconomyPlan,
    IntelPlan,
    Proposal,
    RelocationEvent,
    SensorTowerPlan,
    SensorTowerSite,
    StructurePlan,
    SurvivalComposition,
)

__all__ = [
    "Command",
    "CompositionPlan",
    "CounterAdaptation",
    "DetectionPlan",
    "Domain",
    "EarlyScoutReport",
    "EconomyPlan",
    "IntelPlan",
    "Proposal",
    "RelocationEvent",
    "SensorTowerPlan",
    "SensorTowerSite",
    "StructurePlan",
    "SurvivalComposition",
]

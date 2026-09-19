"""Domain decisions expressed as plans and unit proposals.

Each subpackage is one planner owning one domain: offense, defense, map control,
intel, economy and structure control. Missions are optional implementation
details for episodic operations; see docs/architecture.md.
"""

from .contracts import (
    Command,
    CompositionPlan,
    CounterAdaptation,
    DetectionPlan,
    Domain,
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
    "EconomyPlan",
    "IntelPlan",
    "Proposal",
    "RelocationEvent",
    "SensorTowerPlan",
    "SensorTowerSite",
    "StructurePlan",
    "SurvivalComposition",
]

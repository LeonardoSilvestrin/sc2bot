"""Domain decisions expressed as plans and unit proposals.

Military groups offense, defense and map control. Intel, economy and structure
control own their respective domains. Missions are optional implementation
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
    "SensorTowerPlan",
    "SensorTowerSite",
    "StructurePlan",
    "SurvivalComposition",
]

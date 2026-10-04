"""Domain decisions about what we already have, expressed as plans and unit
proposals.

Each subpackage is one domain with one planner: offense, defense, map control,
intel and structure control. The planner owns the domain, a mission
(`missions/`) owns an operation, a policy (`policies/`) implements a decision
rule and knowledge (`knowledge/`) holds static domain facts; see
docs/architecture.md. What they all share is in `common/`: the contracts they
hand the Body and what a mission is. What we buy is not a planner's: it is
`bot.ego.economy`'s.
"""

from .common.contracts import (
    Command,
    DetectionPlan,
    Domain,
    EarlyScoutReport,
    IntelPlan,
    Proposal,
    RelocationEvent,
    SensorTowerPlan,
    SensorTowerSite,
    StructurePlan,
)
from .common.mission import (
    CancelMode,
    CancelRequest,
    Lifecycle,
    MissionFeedback,
    MissionStatus,
    MissionView,
)

__all__ = [
    "CancelMode",
    "CancelRequest",
    "Command",
    "DetectionPlan",
    "Domain",
    "EarlyScoutReport",
    "IntelPlan",
    "Lifecycle",
    "MissionFeedback",
    "MissionStatus",
    "MissionView",
    "Proposal",
    "RelocationEvent",
    "SensorTowerPlan",
    "SensorTowerSite",
    "StructurePlan",
]

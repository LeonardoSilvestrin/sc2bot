"""Desired state of controllable structures; see docs/architecture.md.

`planner.StructureControlPlanner` raises and lowers the depots and joins
`policies.relocation`, which lifts a structure out of a stuck Siege Tank's way.
"""

from .planner import StructureConfig, StructureControlPlanner
from .policies.relocation import RelocationConfig

__all__ = ["RelocationConfig", "StructureConfig", "StructureControlPlanner"]

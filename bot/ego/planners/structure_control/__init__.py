"""Desired state of controllable structures; see docs/architecture.md."""

from .planner import StructureConfig, StructureControl
from .relocation import RelocationConfig

__all__ = ["RelocationConfig", "StructureControl", "StructureConfig"]

"""Strategy's spatial boundary: where control is wanted.

The only part of Strategy that carries positions and reads Awareness'
territory. See ``docs/strategy.md``.
"""

from .config import SpatialPolicyConfig
from .model import ControlObjective, ControlTargetKind, SpatialStrategySnapshot
from .policy import derive_control_objectives

__all__ = [
    "ControlObjective",
    "ControlTargetKind",
    "SpatialPolicyConfig",
    "SpatialStrategySnapshot",
    "derive_control_objectives",
]

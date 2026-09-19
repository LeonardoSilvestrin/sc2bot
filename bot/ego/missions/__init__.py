"""CORE: what every planner's missions share.

A planner decides which missions to open, keep or ask to end; a mission is
one concrete operation -- its identity, its phase and its memory -- and turns
what it observes into the proposals of this frame. Neither names a unit: the
Engine grants them. This package holds only what all of them share:

- `lifecycle`: the terminal statuses, the cancel request and its modes;
- `contracts`: the feedback a mission reads and the view it reports.

The concrete missions live with the planner that governs them, in
`planners/<group>/<domain>/missions/`.
"""

from .contracts import MissionFeedback, MissionView
from .lifecycle import CancelMode, CancelRequest, Lifecycle, MissionStatus

__all__ = [
    "CancelMode",
    "CancelRequest",
    "Lifecycle",
    "MissionFeedback",
    "MissionStatus",
    "MissionView",
]

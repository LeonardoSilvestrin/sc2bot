"""LIFECYCLE: how every mission is born, asked to end and ends.

A mission's lifecycle is small and shared: ACTIVE, then one terminal status.
Its phases (assembling, advancing, lapping ...) are its own. Only the mission
reaches a terminal status:

- COMPLETED or FAILED, by its own operational conditions;
- CANCELLED, after its planner asked for it (`request_cancel`) and the
  mission wound down: at once (IMMEDIATE), so the units it held go to other
  proposals in the same allocation, or after a withdrawal (GRACEFUL), which
  keeps proposing until its own release condition or deadline.

A terminal mission proposes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MissionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CancelMode(str, Enum):
    # Drop every proposal now: the units are free for this frame's allocation.
    IMMEDIATE = "IMMEDIATE"
    # Withdraw first, then end: the mission keeps proposing until it releases.
    GRACEFUL = "GRACEFUL"


@dataclass(frozen=True, slots=True)
class CancelRequest:
    mode: CancelMode
    reason: str
    time: float


@dataclass(slots=True)
class Lifecycle:
    """Identity, terminal status and the pending cancel request of a mission.

    The planner writes only `request_cancel`; the mission writes `end`."""

    mission_id: str
    status: MissionStatus = MissionStatus.ACTIVE
    cancel: CancelRequest | None = field(default=None)

    @property
    def active(self) -> bool:
        return self.status is MissionStatus.ACTIVE

    def request_cancel(self, mode: CancelMode, reason: str, now: float) -> None:
        """Ask the mission to end. A graceful request never softens an
        immediate one; an immediate one escalates a graceful one."""

        if not self.active:
            return
        if self.cancel is None or (
            mode is CancelMode.IMMEDIATE and self.cancel.mode is CancelMode.GRACEFUL
        ):
            self.cancel = CancelRequest(mode, reason, now)

    def end(self, status: MissionStatus) -> None:
        if status is MissionStatus.ACTIVE:
            raise ValueError("a mission ends in a terminal status")
        if status is MissionStatus.CANCELLED and self.cancel is None:
            raise ValueError("only a requested cancel ends a mission as CANCELLED")
        self.status = status

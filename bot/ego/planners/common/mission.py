"""MISSION: what every mission is, whichever planner owns it.

A mission is an episodic operation a planner governs (the concrete ones live
under their planner, in `<planner>/missions/`). What they share is here: how a
mission is born, asked to end and ends, what it reads, and what it reports.

A mission's lifecycle is small and shared: ACTIVE, then one terminal status.
Its phases (assembling, advancing, lapping ...) are its own. Only the mission
reaches a terminal status:

- COMPLETED or FAILED, by its own operational conditions;
- CANCELLED, after its planner asked for it (`request_cancel`) and the
  mission wound down: at once (IMMEDIATE), so the units it held go to other
  proposals in the same allocation, or after a withdrawal (GRACEFUL), which
  keeps proposing until its own release condition or deadline.

A terminal mission proposes nothing.

A mission reads last frame's grants as feedback (`MissionFeedback`), never as
a second record of who owns what: the Engine alone owns units, and it never
touches a mission. After each step a mission reports itself as an immutable
`MissionView`, for the log and for whoever sits above its planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.body.engine import EngineResult, Grant


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


@dataclass(frozen=True, slots=True)
class MissionFeedback:
    """What the Engine granted a mission's proposals in the last allocation."""

    grants: tuple[Grant, ...] = ()

    @classmethod
    def of(cls, result: EngineResult | None, mission_id: str) -> MissionFeedback:
        if result is None:
            return cls()
        return cls(
            tuple(grant for grant in result.grants if grant.proposal.mission_id == mission_id)
        )

    @property
    def tags(self) -> frozenset[int]:
        return frozenset(tag for grant in self.grants for tag in grant.tags)

    @property
    def power(self) -> float:
        return sum(grant.power for grant in self.grants)


@dataclass(frozen=True, slots=True)
class MissionView:
    """An immutable summary of a mission after this frame's step."""

    mission_id: str
    # The planner that governs it.
    owner: str
    kind: str
    status: MissionStatus
    phase: str
    since: float
    # Why the phase, or the terminal status, was entered.
    reason: str
    cancel: CancelRequest | None
    # The proposals it made this frame.
    proposals: tuple[str, ...]
    # What the last allocation granted it.
    granted_units: int
    granted_power: float

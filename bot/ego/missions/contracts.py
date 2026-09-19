"""CONTRACTS: what a mission reads and what it reports.

A mission reads last frame's grants as feedback (`MissionFeedback`), never as
a second record of who owns what: the Engine alone owns units, and it never
touches a mission. After each step a mission reports itself as an immutable
`MissionView`, for the log and for whoever sits above its planner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .lifecycle import CancelRequest, MissionStatus

if TYPE_CHECKING:
    from bot.body.engine import EngineResult, Grant


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

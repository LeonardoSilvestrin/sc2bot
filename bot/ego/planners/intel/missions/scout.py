"""ScoutMission: one scout through the enemy main.

The start location first, then a lap along the edge of the main's region, one
waypoint per angular sector, beginning on the side it arrives from. The
mission asks for one SCV (REQUESTING) and laps once it set out (LAPPING). It
completes once every waypoint was seen, and fails when the scout is lost or
`LAP_TIMEOUT` after it set out; the SCV then goes back to mining. A cancel
request ends it at once: a worker has nothing to walk back from.

Priority is the share of the route still unseen. Workers are a pool of their
own in the Engine, so it only orders the log.
"""

from __future__ import annotations

from collections.abc import Sequence, Set

from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState
from bot.ego.planners import Command, Proposal
from bot.ego.planners.missions import (
    CancelMode,
    Lifecycle,
    MissionFeedback,
    MissionStatus,
    MissionView,
)

OWNER = "intel"
KIND = "scout"
# One id for every scout.
PROPOSAL_ID = OWNER
SCOUT_TYPES = frozenset({UnitTypeId.SCV})
# A scout that cannot finish the lap by then (a wall, a chase) goes home.
LAP_TIMEOUT = 90.0


class ScoutMission:
    # Asking for a SCV; none has set out yet.
    REQUESTING = "REQUESTING"
    # A scout is on the route.
    LAPPING = "LAPPING"

    def __init__(self, mission_id: str, route: tuple[Point2, ...], now: float) -> None:
        self.lifecycle = Lifecycle(mission_id)
        self.route = route
        self.phase = self.REQUESTING
        self.since = now
        self.reason = "mineral_line_ready"
        self.set_out: float | None = None

    @property
    def mission_id(self) -> str:
        return self.lifecycle.mission_id

    @property
    def status(self) -> MissionStatus:
        return self.lifecycle.status

    @property
    def active(self) -> bool:
        return self.lifecycle.active

    def request_cancel(self, mode: CancelMode, reason: str, now: float) -> None:
        self.lifecycle.request_cancel(mode, reason, now)

    def observe(self, attention: AttentionState) -> None:
        """Notice the scout set out: the scout behavior gives whoever the
        Engine granted the SCOUTING role."""

        if self.set_out is not None or not self.active:
            return
        if _scouting(attention):
            now = attention.time
            self.set_out = now
            self.phase, self.since, self.reason = self.LAPPING, now, "scout_set_out"

    def step(
        self, attention: AttentionState, seen: Set[int], feedback: MissionFeedback
    ) -> tuple[Proposal, ...]:
        """`seen`: the route's waypoints seen so far, by index."""

        if not self.active:
            return ()
        now = attention.time
        if len(seen) == len(self.route):
            return self._end(MissionStatus.COMPLETED, "route_seen", now)
        self.observe(attention)
        cancel = self.lifecycle.cancel
        if cancel is not None:
            # A worker has nothing to walk back from: it goes back to mining.
            return self._end(MissionStatus.CANCELLED, cancel.reason, now)
        if self.set_out is not None:
            if not _scouting(attention):
                return self._end(MissionStatus.FAILED, "scout_lost", now)
            if now - self.set_out >= LAP_TIMEOUT:
                return self._end(MissionStatus.FAILED, "lap_timed_out", now)
        waypoint = min(set(range(len(self.route))) - set(seen))
        return (
            Proposal(
                proposal_id=PROPOSAL_ID,
                owner=OWNER,
                priority=(len(self.route) - len(seen)) / len(self.route),
                command=Command.SCOUT,
                target=self.route[waypoint],
                reason="scout_enemy_start" if waypoint == 0 else "lap_enemy_main",
                count=1,
                unit_types=SCOUT_TYPES,
                inputs=(
                    ("workers", float(attention.workers)),
                    ("waypoint", float(waypoint)),
                    ("seen", float(len(seen))),
                    ("waypoints", float(len(self.route))),
                    ("scouting_for", 0.0 if self.set_out is None else now - self.set_out),
                ),
                mission_id=self.mission_id,
            ),
        )

    def view(self, feedback: MissionFeedback, proposals: Sequence[Proposal]) -> MissionView:
        return MissionView(
            mission_id=self.mission_id,
            owner=OWNER,
            kind=KIND,
            status=self.status,
            phase=self.phase,
            since=self.since,
            reason=self.reason,
            cancel=self.lifecycle.cancel,
            proposals=tuple(proposal.proposal_id for proposal in proposals),
            granted_units=len(feedback.tags),
            granted_power=feedback.power,
        )

    def _end(self, status: MissionStatus, reason: str, now: float) -> tuple[Proposal, ...]:
        self.since, self.reason = now, reason
        self.lifecycle.end(status)
        return ()



def _scouting(attention: AttentionState) -> bool:
    return any(
        unit.type_id in SCOUT_TYPES and unit.role == UnitRole.SCOUTING.name
        for unit in attention.own_units
    )


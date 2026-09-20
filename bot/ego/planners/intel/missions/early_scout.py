"""The first SCV, reading the enemy's opening.

One operation with a lifecycle of its own: the scout checks the enemy natural
on the way in, laps the main for production, gas, tech and units, comes back to
the natural it found empty to close the window it went up in, tries to confirm
the third, and then keeps watching until the opening is over. At any point the
Intel planner can send it looking for a proxy instead.

```text
REQUESTING -> CHECK_NATURAL -> ENTER_MAIN -> CIRCLE_MAIN -> RECHECK_NATURAL
           -> CHECK_THIRD -> SURVEIL -> COMPLETE   (PROXY_SEARCH whenever asked)
```

The sequence adapts to what is found: a natural that was already standing is
not rechecked, a main that cannot be entered is not lapped forever, and a
phase that stops being worth its time hands over to the next one.

`SURVEIL` is the one phase that does not end by itself. An empty third is an
answer with a shelf life -- it says nothing about the third that goes up two
minutes later -- so instead of parking on it, the scout walks a round of the
places worth watching: the natural, the third, the way out of the enemy main
and the main itself. It always heads for whichever of them it has looked at
least recently, which turns into a rotation, rechecks both expansions on its
own and keeps production, tech, gas and what leaves the base coming in. Only
the end of the opening window closes it.

The mission records nothing. What it makes visible, Attention records
(`bot.attention.opening`), which is what the phases then read.
"""

from __future__ import annotations

from collections.abc import Sequence, Set
from dataclasses import dataclass
from enum import Enum

from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, ExpansionStatus, OpeningObservations
from bot.ego.missions import CancelMode, Lifecycle, MissionFeedback, MissionStatus, MissionView
from bot.ego.planners import Command, EarlyScoutReport, Proposal

OWNER = "intel"
KIND = "early_scout"
# The proposal keeps the old id: logs, viewer and benches follow it.
PROPOSAL_ID = OWNER
SCOUT_TYPES = frozenset({UnitTypeId.SCV})


class ScoutPhase(str, Enum):
    # Asking for an SCV; nothing is being scouted yet.
    REQUESTING = "REQUESTING"
    CHECK_NATURAL = "CHECK_NATURAL"
    ENTER_MAIN = "ENTER_MAIN"
    CIRCLE_MAIN = "CIRCLE_MAIN"
    RECHECK_NATURAL = "RECHECK_NATURAL"
    CHECK_THIRD = "CHECK_THIRD"
    # Keeps watching what was already answered; ends with the opening itself.
    SURVEIL = "SURVEIL"
    PROXY_SEARCH = "PROXY_SEARCH"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True, slots=True)
class ScoutWindow:
    """The clock of one early scout, in seconds of game time."""

    # A natural found empty is looked at again this long afterwards: the two
    # readings are the window the expansion went up in.
    recheck_after: float = 25.0
    # Longest one look may hold the scout **after it got there** before the
    # next phase takes over: a phase that has not arrived yet is walking, not
    # stalling.
    check_for: float = 30.0
    circle_for: float = 60.0
    search_for: float = 60.0
    # And the longest that walk may take before the phase gives up on it.
    travel_for: float = 75.0
    # Longest the patrol waits on one place before going round to the next:
    # a place it cannot reach does not hold up the round.
    surveil_step: float = 20.0
    # A third found after this game time says nothing about the opening any
    # more, and after this one the opening is over: both are clock readings,
    # not durations, because that is what an opening is measured in.
    third_until: float = 330.0
    until: float = 300.0


# A scout this close to what it was sent to is looking at it.
ARRIVAL = 10.0
# What each phase is worth against the rest of the frame's proposals: checking
# the natural and hunting a proxy are the answers we need soonest.
PHASE_PRIORITY: dict[ScoutPhase, float] = {
    ScoutPhase.REQUESTING: 1.0,
    ScoutPhase.CHECK_NATURAL: 1.0,
    ScoutPhase.ENTER_MAIN: 0.95,
    ScoutPhase.CIRCLE_MAIN: 0.9,
    ScoutPhase.RECHECK_NATURAL: 0.8,
    ScoutPhase.CHECK_THIRD: 0.6,
    ScoutPhase.SURVEIL: 0.5,
    ScoutPhase.PROXY_SEARCH: 1.0,
    ScoutPhase.COMPLETE: 0.0,
}


class EarlyScoutMission:
    def __init__(
        self,
        mission_id: str,
        route: tuple[Point2, ...],
        now: float,
        *,
        natural: Point2 | None = None,
        third: Point2 | None = None,
        proxy_route: tuple[Point2, ...] = (),
        watchpoints: tuple[Point2, ...] = (),
        window: ScoutWindow | None = None,
    ) -> None:
        self.lifecycle = Lifecycle(mission_id)
        # The enemy start and the lap around its main.
        self.route = route
        self.natural = natural
        self.third = third
        self.proxy_route = proxy_route
        # The round the surveillance walks: both expansions first, then the
        # ways out of the enemy main, then the main itself.
        self.ring = tuple(
            dict.fromkeys(
                point
                for point in (natural, third, *watchpoints, *route[1:])
                if point is not None
            )
        )
        self.window = window or ScoutWindow()
        self.phase = ScoutPhase.REQUESTING
        self.previous: ScoutPhase | None = None
        self.since = now
        self.opened = now
        self.reason = "mineral_line_ready"
        self.set_out: float | None = None
        # When the planner ordered the proxy search, and why.
        self.proxy_ordered: float | None = None
        self.proxy_reason: str | None = None
        self._proxy_index = 0
        self._target: Point2 | None = None
        # When the scout first reached what this phase sent it to.
        self._arrived: float | None = None
        # When each place of the round was last looked at, and the one the
        # patrol is walking to now.
        self._seen: list[float] = [now] * len(self.ring)
        self._watching: int | None = None
        self._watching_since = now

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

    def search_proxy(self, reason: str, now: float) -> bool:
        """Send the scout looking for a proxy; True when it took the order."""

        if not self.active or self.phase in (ScoutPhase.PROXY_SEARCH, ScoutPhase.COMPLETE):
            return False
        if not self.proxy_route:
            return False
        self.proxy_ordered, self.proxy_reason = now, reason
        self._enter(ScoutPhase.PROXY_SEARCH, reason, now)
        return True

    def observe(self, attention: AttentionState) -> None:
        """The frame an SCV takes the scouting role is the frame it sets out."""

        if self.set_out is not None or not self.active:
            return
        if _scouting(attention):
            self.set_out = attention.time

    def step(
        self, attention: AttentionState, seen: Set[int], feedback: MissionFeedback
    ) -> tuple[Proposal, ...]:
        if not self.active:
            return ()
        now = attention.time
        self.observe(attention)
        cancel = self.lifecycle.cancel
        if cancel is not None:
            return self._end(MissionStatus.CANCELLED, cancel.reason, now)
        if self.set_out is not None and not _scouting(attention):
            return self._end(MissionStatus.FAILED, "scout_lost", now)
        if now >= self.window.until:
            return self._end(MissionStatus.COMPLETED, "opening_over", now)
        self._note_arrival(attention, feedback)
        self._look_around(attention)
        self._advance(attention, seen)
        if self.phase is ScoutPhase.COMPLETE:
            return self._end(MissionStatus.COMPLETED, self.reason, now)
        target = self._target_for(attention, seen)
        self._target = target
        if target is None:
            return self._end(MissionStatus.COMPLETED, "nowhere_left_to_look", now)
        return (
            Proposal(
                proposal_id=PROPOSAL_ID,
                owner=OWNER,
                priority=self._priority(seen),
                command=Command.SCOUT,
                target=target,
                reason=self.phase.value.lower(),
                count=1,
                unit_types=SCOUT_TYPES,
                inputs=(
                    ("workers", float(attention.workers)),
                    ("seen", float(len(seen))),
                    ("waypoints", float(len(self.route))),
                    ("scouting_for", 0.0 if self.set_out is None else now - self.set_out),
                    ("phase_for", now - self.since),
                    ("arrived", -1.0 if self._arrived is None else self._arrived),
                    ("main_coverage", attention.enemy_opening.main_scout_coverage),
                    ("proxy_points", float(len(self.proxy_route))),
                ),
                mission_id=self.mission_id,
            ),
        )

    def report(self) -> EarlyScoutReport:
        return EarlyScoutReport(
            mission_id=self.mission_id,
            phase=self.phase.value,
            previous=None if self.previous is None else self.previous.value,
            since=self.since,
            reason=self.reason,
            status=self.status.value,
            target=self._target,
            proxy_search=self.proxy_ordered is not None,
            inputs=(
                ("set_out", -1.0 if self.set_out is None else self.set_out),
                ("proxy_ordered", -1.0 if self.proxy_ordered is None else self.proxy_ordered),
                ("proxy_index", float(self._proxy_index)),
                ("proxy_points", float(len(self.proxy_route))),
                ("watching", -1.0 if self._watching is None else float(self._watching)),
                ("watchpoints", float(len(self.ring))),
            ),
        )

    def view(self, feedback: MissionFeedback, proposals: Sequence[Proposal]) -> MissionView:
        return MissionView(
            mission_id=self.mission_id,
            owner=OWNER,
            kind=KIND,
            status=self.status,
            phase=self.phase.value,
            since=self.since,
            reason=self.reason,
            cancel=self.lifecycle.cancel,
            proposals=tuple(proposal.proposal_id for proposal in proposals),
            granted_units=len(feedback.tags),
            granted_power=feedback.power,
        )

    # --- phases ---------------------------------------------------------------

    def _note_arrival(self, attention: AttentionState, feedback: MissionFeedback) -> None:
        """A phase's clock starts when its scout gets there, not when it set
        off: the walk across the map is not a phase standing still."""

        if self._arrived is not None or self._target is None:
            return
        tags = feedback.tags
        for unit in attention.own_units:
            if unit.type_id not in SCOUT_TYPES:
                continue
            if tags and unit.tag not in tags:
                continue
            if not tags and unit.role != UnitRole.SCOUTING.name:
                continue
            if unit.position.distance_to(self._target) <= ARRIVAL:
                self._arrived = attention.time
                return

    def _advance(self, attention: AttentionState, seen: Set[int]) -> None:
        """Walk the phases the frame already settled, at most one round."""

        for _ in range(len(ScoutPhase)):
            step = self._next(attention, seen)
            if step is None:
                return
            phase, reason = step
            self._enter(phase, reason, attention.time)

    def _next(
        self, attention: AttentionState, seen: Set[int]
    ) -> tuple[ScoutPhase, str] | None:
        opening = attention.enemy_opening
        now = attention.time
        phase = self.phase
        if phase is ScoutPhase.REQUESTING:
            if self.set_out is not None:
                return (ScoutPhase.CHECK_NATURAL, "scout_set_out")
            return None
        if phase is ScoutPhase.CHECK_NATURAL:
            if self.natural is None:
                return (ScoutPhase.ENTER_MAIN, "no_natural_known")
            if opening.natural_checked:
                return (ScoutPhase.ENTER_MAIN, "natural_checked")
            if self._out_of_time(now, self.window.check_for):
                return (ScoutPhase.ENTER_MAIN, "check_timed_out")
            return None
        if phase is ScoutPhase.ENTER_MAIN:
            if opening.main_scout_coverage > 0.0 or attention.is_visible(self.route[0]):
                return (ScoutPhase.CIRCLE_MAIN, "main_reached")
            if self._out_of_time(now, self.window.check_for):
                return (ScoutPhase.CIRCLE_MAIN, "entry_timed_out")
            return None
        if phase is ScoutPhase.CIRCLE_MAIN:
            lapped = len(seen) >= len(self.route)
            out_of_time = self._out_of_time(now, self.window.circle_for)
            if not lapped and not out_of_time:
                return None
            reason = "main_lapped" if lapped else "lap_timed_out"
            if self._recheck_due(opening, now):
                return (ScoutPhase.RECHECK_NATURAL, reason)
            # Nothing to recheck yet: keep lapping while the lap is worth time.
            if self._recheck_pending(opening) and not out_of_time:
                return None
            return (ScoutPhase.CHECK_THIRD, reason)
        if phase is ScoutPhase.RECHECK_NATURAL:
            if opening.natural.status is ExpansionStatus.PRESENT:
                return (ScoutPhase.CHECK_THIRD, "natural_found")
            checked = opening.natural.last_checked_at
            if checked is not None and checked >= self.since:
                return (ScoutPhase.CHECK_THIRD, "natural_still_absent")
            if self._out_of_time(now, self.window.check_for):
                return (ScoutPhase.CHECK_THIRD, "recheck_timed_out")
            return None
        if phase is ScoutPhase.CHECK_THIRD:
            # Whatever the third answered, the answer has a shelf life: the
            # scout keeps watching instead of standing on it.
            if self.third is None:
                return (ScoutPhase.SURVEIL, "no_third_known")
            if opening.third.status is ExpansionStatus.PRESENT:
                return (ScoutPhase.SURVEIL, "third_found")
            if opening.third.status is ExpansionStatus.ABSENT_CONFIRMED:
                return (ScoutPhase.SURVEIL, "third_empty")
            if now >= self.window.third_until:
                return (ScoutPhase.SURVEIL, "third_window_over")
            return None
        if phase is ScoutPhase.SURVEIL:
            # The round has no end of its own: the opening window closes it.
            return None
        if phase is ScoutPhase.PROXY_SEARCH:
            self._proxy_index = _walked(self.proxy_route, self._proxy_index, attention)
            if opening.proxy_structures_seen > 0:
                return (ScoutPhase.COMPLETE, "proxy_found")
            if self._proxy_index >= len(self.proxy_route):
                return (ScoutPhase.COMPLETE, "proxy_search_done")
            if self._out_of_time(now, self.window.search_for):
                return (ScoutPhase.COMPLETE, "proxy_search_timed_out")
            return None
        return None

    def _out_of_time(self, now: float, limit: float) -> bool:
        """A phase runs out either after `limit` seconds of being there, or
        after `travel_for` seconds of never getting there at all."""

        if self._arrived is None:
            return now - self.since >= self.window.travel_for
        return now - self._arrived >= limit

    def _recheck_due(self, opening: OpeningObservations, now: float) -> bool:
        """An expansion found empty is worth a second look once enough time
        has passed for one to have gone up."""

        natural = opening.natural
        if natural.status is not ExpansionStatus.ABSENT_CONFIRMED or natural.absent_at is None:
            return False
        return now - natural.absent_at >= self.window.recheck_after

    def _recheck_pending(self, opening: OpeningObservations) -> bool:
        return opening.natural.status is ExpansionStatus.ABSENT_CONFIRMED

    def _enter(self, phase: ScoutPhase, reason: str, now: float) -> None:
        if phase is self.phase:
            return
        self.previous, self.phase = self.phase, phase
        self.since, self.reason = now, reason
        self._arrived = None

    def _target_for(self, attention: AttentionState, seen: Set[int]) -> Point2 | None:
        phase = self.phase
        if phase in (ScoutPhase.REQUESTING, ScoutPhase.CHECK_NATURAL, ScoutPhase.RECHECK_NATURAL):
            return self.natural or self.route[0]
        if phase is ScoutPhase.ENTER_MAIN:
            return self.route[0]
        if phase is ScoutPhase.CIRCLE_MAIN:
            unseen = set(range(len(self.route))) - set(seen)
            return self.route[min(unseen)] if unseen else self.route[0]
        if phase is ScoutPhase.CHECK_THIRD:
            return self.third or self.route[0]
        if phase is ScoutPhase.SURVEIL:
            return self._patrol(attention)
        if phase is ScoutPhase.PROXY_SEARCH:
            self._proxy_index = _walked(self.proxy_route, self._proxy_index, attention)
            if self._proxy_index < len(self.proxy_route):
                return self.proxy_route[self._proxy_index]
            return None
        return None

    def _look_around(self, attention: AttentionState) -> None:
        """Everything the round can see right now has just been looked at."""

        now = attention.time
        for index, point in enumerate(self.ring):
            if attention.is_visible(point):
                self._seen[index] = now

    def _patrol(self, attention: AttentionState) -> Point2 | None:
        """The place of the round looked at least recently. Picking by
        staleness is what turns the round into a rotation: a place just seen
        goes to the back, so the scout never stands on an answer it already
        has, and the natural and the third come round again on their own."""

        if not self.ring:
            return self.route[0]
        now = attention.time
        index = self._watching
        looked = index is not None and self._seen[index] >= self._watching_since
        gave_up = index is not None and now - self._watching_since >= self.window.surveil_step
        if index is not None and gave_up and not looked:
            # It could not get there; that does not hold up the round.
            self._seen[index] = now
        if index is None or looked or gave_up:
            self._watching = min(range(len(self.ring)), key=lambda at: (self._seen[at], at))
            self._watching_since = now
        return self.ring[self._watching]

    def _priority(self, seen: Set[int]) -> float:
        base = PHASE_PRIORITY[self.phase]
        if self.phase is not ScoutPhase.CIRCLE_MAIN:
            return base
        left = (len(self.route) - len(seen)) / len(self.route)
        return base * max(0.3, left)

    def _end(self, status: MissionStatus, reason: str, now: float) -> tuple[Proposal, ...]:
        self.previous, self.phase = self.phase, ScoutPhase.COMPLETE
        self.since, self.reason = now, reason
        self._target = None
        self.lifecycle.end(status)
        return ()


def _walked(route: tuple[Point2, ...], index: int, attention: AttentionState) -> int:
    """How far down the route the scout has looked: a point in vision is done."""

    while index < len(route) and attention.is_visible(route[index]):
        index += 1
    return index


def _scouting(attention: AttentionState) -> bool:
    return any(
        unit.type_id in SCOUT_TYPES and unit.role == UnitRole.SCOUTING.name
        for unit in attention.own_units
    )

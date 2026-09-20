"""Whether the passages of the map are open right now.

The `MapTopology` is built once and never again: regions, passage ids and the
expansion each one belongs to are the map's identity and hold for the whole
game. What a mineral wall or a pile of rocks changes is one field --
`MapPassage.state` -- and this is where that field is kept honest.

The rules are the ones the game itself follows:

* a mineral wall that still has minerals -> ``CLOSED``;
* a destructible that is still standing -> ``CLOSED``;
* every blocker of the passage gone -> ``OPEN``.

Nothing is rebuilt to answer that. Each passage carries the tags of the
neutral objects that seal it, and a frame only has to ask which of those tags
the game still lists. Comparing the surviving tags avoids any topology work
on frames where the blockers have not changed.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass, replace

from sc2.position import Point2

from .map import MapView
from .topology import (
    CLOSED,
    OPEN,
    UNKNOWN,
    BlockerType,
    MapPassage,
    MapTopology,
    PassageState,
)

__all__ = [
    "PassageChange",
    "PassageWatch",
    "changes_between",
    "passage_states",
]


@dataclass(frozen=True, slots=True)
class PassageChange:
    """One passage that changed state, and what it was blocked by."""

    passage_id: str
    before: PassageState
    after: PassageState
    position: Point2
    regions: tuple[str, ...]
    blocker_type: BlockerType | None
    # Blockers of this passage the game still lists.
    blockers_left: int

    @property
    def transition(self) -> str:
        return f"{self.before.upper()} -> {self.after.upper()}"


def passage_states(
    topology: MapTopology, alive: Collection[int] | None
) -> dict[str, PassageState]:
    """The state every blocked passage is in, given the blocker tags the game
    still lists. ``alive`` of None is "we could not look": a passage we hold
    blockers for goes ``UNKNOWN`` rather than falsely open."""

    states: dict[str, PassageState] = {}
    for passage in topology.passages:
        if not passage.has_blockers:
            continue
        if alive is None:
            states[passage.passage_id] = UNKNOWN
        elif any(tag in alive for tag in passage.blocker_tags):
            states[passage.passage_id] = CLOSED
        else:
            states[passage.passage_id] = OPEN
    return states


def changes_between(
    before: MapTopology, after: MapTopology, alive: Collection[int] | None
) -> tuple[PassageChange, ...]:
    was = {passage.passage_id: passage.state for passage in before.passages}
    return tuple(
        PassageChange(
            passage_id=passage.passage_id,
            before=was.get(passage.passage_id, passage.state),
            after=passage.state,
            position=passage.position,
            regions=passage.regions,
            blocker_type=passage.blocker_type,
            blockers_left=_left(passage, alive),
        )
        for passage in after.passages
        if was.get(passage.passage_id, passage.state) != passage.state
    )


@dataclass(slots=True)
class PassageWatch:
    """What Attention remembers about the blockers between frames.

    It holds no map of its own: the topology it is handed names the tags, and
    the `MapView` it hands back is the same object until a passage really
    changed, so anything that caches per map -- staging's `Ground`, above all
    -- rebuilds exactly once per opened passage and never per frame.
    """

    _watched: frozenset[int] | None = None
    _alive_tags: frozenset[int] | None = None
    _observed: bool = False

    def refresh(self, bot, map_view: MapView) -> tuple[MapView, tuple[PassageChange, ...]]:
        topology = map_view.topology
        if self._watched is None:
            self._watched = frozenset(
                tag for passage in topology.passages for tag in passage.blocker_tags
            )
        if not self._watched:
            return map_view, ()
        alive = _alive(bot, self._watched)
        if self._observed and alive == self._alive_tags:
            return map_view, ()
        self._alive_tags = alive
        self._observed = True
        updated = topology.with_passage_states(passage_states(topology, alive))
        if updated is topology:
            return map_view, ()
        return replace(map_view, topology=updated), changes_between(
            topology, updated, alive
        )


def _left(passage: MapPassage, alive: Collection[int] | None) -> int:
    if alive is None:
        return len(passage.blocker_tags)
    return sum(1 for tag in passage.blocker_tags if tag in alive)


def _alive(bot, watched: frozenset[int]) -> frozenset[int] | None:
    """The watched tags the game still lists; None unless every source
    answered, so that a half-read never opens a passage by itself."""

    found: set[int] = set()
    for name in ("destructables", "mineral_field"):
        units = _units(bot, name)
        if units is None:
            return None
        found.update(
            tag
            for unit in units
            if (tag := _tag(unit)) in watched
            and (
                name != "mineral_field"
                or getattr(unit, "is_snapshot", False)
                or getattr(unit, "mineral_contents", 1) > 0
            )
        )
    return frozenset(found)


def _units(bot, name: str) -> Iterable | None:
    try:
        return tuple(getattr(bot, name))
    except (AttributeError, RuntimeError, TypeError):
        return None


def _tag(unit) -> int | None:
    try:
        return int(unit.tag)
    except (AttributeError, TypeError, ValueError):
        return None

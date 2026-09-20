"""What the early game showed of the enemy's opening, and when.

`OpeningObservations` is a record of facts: an expansion was checked and was
empty at 1:31 and had a townhall at 1:58; two Gateways were first seen at 1:47;
the main is 81 % scouted. It says nothing about what any of that means -- that
is `bot.awareness.opening`.

The three expansion states are not interchangeable: `UNKNOWN` is "nobody
looked", `ABSENT_CONFIRMED` is "we looked and there was nothing", `PRESENT` is
"a townhall stands there". An absence is only ever claimed for a point the
frame had in vision.

`OpeningWatch` carries the record across frames: every frame it folds what
`observe` perceived into the one it holds, and only the first `OPENING_WINDOW`
seconds are recorded -- afterwards the opening is over and the record freezes
as the game left it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from .map import BASE_SNAP_DISTANCE, MapView
from .units import is_army

if TYPE_CHECKING:
    from .frame import AttentionState

# How long the opening is worth recording, in seconds.
OPENING_WINDOW = 300.0
GAS_STRUCTURES = frozenset(
    {
        UnitTypeId.REFINERY,
        UnitTypeId.REFINERYRICH,
        UnitTypeId.ASSIMILATOR,
        UnitTypeId.ASSIMILATORRICH,
        UnitTypeId.EXTRACTOR,
        UnitTypeId.EXTRACTORRICH,
    }
)
TOWNHALLS = frozenset(
    {
        UnitTypeId.COMMANDCENTER,
        UnitTypeId.ORBITALCOMMAND,
        UnitTypeId.PLANETARYFORTRESS,
        UnitTypeId.NEXUS,
        UnitTypeId.HATCHERY,
        UnitTypeId.LAIR,
        UnitTypeId.HIVE,
    }
)


class ExpansionStatus(str, Enum):
    # Nobody has looked at the spot yet.
    UNKNOWN = "UNKNOWN"
    # The spot was in vision and carried no townhall.
    ABSENT_CONFIRMED = "ABSENT_CONFIRMED"
    # A townhall was seen standing there.
    PRESENT = "PRESENT"


@dataclass(frozen=True, slots=True)
class ExpansionObservation:
    status: ExpansionStatus = ExpansionStatus.UNKNOWN
    # The last time the spot was in vision, whatever was found there.
    last_checked_at: float | None = None
    # When a townhall was first seen standing there.
    first_seen_at: float | None = None
    # The last time the spot was in vision and empty.
    absent_at: float | None = None

    @property
    def appeared_between(self) -> tuple[float, float] | None:
        """The window the townhall went up in: last seen empty, first seen
        standing. None until both halves were observed."""

        if self.first_seen_at is None or self.absent_at is None:
            return None
        if self.absent_at >= self.first_seen_at:
            return None
        return (self.absent_at, self.first_seen_at)


@dataclass(frozen=True, slots=True)
class StructureObservation:
    # Distinct structures of the type seen at any point, ever.
    count_seen: int = 0
    first_seen_at: float | None = None
    last_seen_at: float | None = None


EMPTY_STRUCTURE = StructureObservation()


@dataclass(frozen=True, slots=True)
class OpeningObservations:
    """Every fact the early game handed us about the enemy's opening."""

    enemy_race: Race = Race.NoRace
    natural: ExpansionObservation = ExpansionObservation()
    third: ExpansionObservation = ExpansionObservation()
    # Every enemy structure type seen, by type name.
    structures: tuple[tuple[UnitTypeId, StructureObservation], ...] = ()
    gases_seen: int = 0
    workers_seen: int = 0
    early_combat_units_seen: int = 0
    # Enemy structures seen closer to our start than to their own.
    proxy_structures_seen: int = 0
    # Share of the enemy main ever held in vision, in [0, 1].
    main_scout_coverage: float = 0.0
    # When the record last learned something new; None while it is empty.
    last_updated: float | None = None

    @property
    def natural_checked(self) -> bool:
        return self.natural.status is not ExpansionStatus.UNKNOWN

    @property
    def third_checked(self) -> bool:
        return self.third.status is not ExpansionStatus.UNKNOWN

    @property
    def race_known(self) -> bool:
        return self.enemy_race not in (Race.NoRace, Race.Random)

    def structure(self, type_id: UnitTypeId) -> StructureObservation:
        for seen_type, observation in self.structures:
            if seen_type is type_id:
                return observation
        return EMPTY_STRUCTURE

    def count(self, types: Iterable[UnitTypeId]) -> int:
        """How many structures of these types were seen, in all."""

        wanted = frozenset(types)
        return sum(
            observation.count_seen for type_id, observation in self.structures if type_id in wanted
        )

    def first_seen(self, types: Iterable[UnitTypeId]) -> float | None:
        """When the first structure of these types was seen; None for none."""

        wanted = frozenset(types)
        times = [
            observation.first_seen_at
            for type_id, observation in self.structures
            if type_id in wanted and observation.first_seen_at is not None
        ]
        return min(times) if times else None

    def types_seen(self, types: Iterable[UnitTypeId]) -> int:
        """How many distinct types among these were seen at all."""

        wanted = frozenset(types)
        return sum(
            1
            for type_id, observation in self.structures
            if type_id in wanted and observation.count_seen > 0
        )


EMPTY = OpeningObservations()


class OpeningWatch:
    """Folds every frame into one `OpeningObservations` for the whole opening."""

    def __init__(self, *, window: float = OPENING_WINDOW) -> None:
        self.window = window
        self.observations = EMPTY
        # Distinct tags already counted, so a structure seen twice counts once.
        self._structures: dict[UnitTypeId, set[int]] = {}
        self._workers: set[int] = set()
        self._combat: set[int] = set()
        self._gases: set[int] = set()
        self._proxies: set[int] = set()
        # The enemy main's lattice samples, and which of them were ever seen.
        self._map: MapView | None = None
        self._main_xs = np.zeros(0, dtype=int)
        self._main_ys = np.zeros(0, dtype=int)
        self._main_seen = np.zeros(0, dtype=bool)
        self._natural: Point2 | None = None
        self._third: Point2 | None = None

    def observe(self, attention: AttentionState) -> OpeningObservations:
        """The record after this frame; unchanged once the opening is over."""

        now = attention.time
        if now > self.window:
            return self.observations
        self._read_map(attention.map)
        previous = self.observations
        observations = replace(
            previous,
            enemy_race=previous.enemy_race if previous.race_known else attention.enemy_race,
            natural=self._expansion(attention, previous.natural, self._natural),
            third=self._expansion(attention, previous.third, self._third),
            structures=self._structures_seen(attention),
            gases_seen=len(self._gases),
            workers_seen=self._counted(self._workers, attention, worker=True),
            early_combat_units_seen=self._counted(self._combat, attention, worker=False),
            proxy_structures_seen=len(self._proxies),
            main_scout_coverage=self._coverage(attention),
        )
        # The race comes from the lobby, not from the scout: knowing it is
        # not having observed anything.
        if replace(observations, enemy_race=previous.enemy_race) != previous:
            observations = replace(observations, last_updated=now)
        self.observations = observations
        return observations

    def _read_map(self, map_view: MapView) -> None:
        if map_view is self._map:
            return
        self._map = map_view
        self._natural = map_view.enemy_natural
        self._third = map_view.enemy_third
        topology = map_view.topology
        region = (
            None
            if topology.enemy_start_region is None
            else topology.region(topology.enemy_start_region)
        )
        samples = () if region is None else region.sample_indices
        points = [map_view.lattice[index] for index in samples]
        self._main_xs = np.array([int(point.x) for point in points], dtype=int)
        self._main_ys = np.array([int(point.y) for point in points], dtype=int)
        self._main_seen = np.zeros(len(points), dtype=bool)

    def _expansion(
        self,
        attention: AttentionState,
        previous: ExpansionObservation,
        position: Point2 | None,
    ) -> ExpansionObservation:
        if position is None or not attention.is_visible(position):
            return previous
        now = attention.time
        townhall = any(
            structure.type_id in TOWNHALLS
            and structure.position.distance_to(position) <= BASE_SNAP_DISTANCE
            for structure in attention.enemy_structures
        )
        if townhall:
            return replace(
                previous,
                status=ExpansionStatus.PRESENT,
                last_checked_at=now,
                first_seen_at=now if previous.first_seen_at is None else previous.first_seen_at,
            )
        # A base that stood there and is gone is still the opening's answer:
        # only an expansion never seen standing can be confirmed absent.
        if previous.status is ExpansionStatus.PRESENT:
            return replace(previous, last_checked_at=now)
        return replace(
            previous,
            status=ExpansionStatus.ABSENT_CONFIRMED,
            last_checked_at=now,
            absent_at=now,
        )

    def _structures_seen(
        self, attention: AttentionState
    ) -> tuple[tuple[UnitTypeId, StructureObservation], ...]:
        now = attention.time
        seen = dict(self.observations.structures)
        own_start = attention.map.own_start
        enemy_start = attention.map.enemy_start
        for structure in attention.enemy_structures:
            tags = self._structures.setdefault(structure.type_id, set())
            tags.add(structure.tag)
            if structure.type_id in GAS_STRUCTURES:
                self._gases.add(structure.tag)
            if structure.position.distance_to(own_start) < structure.position.distance_to(
                enemy_start
            ):
                self._proxies.add(structure.tag)
            first_seen = seen.get(structure.type_id, EMPTY_STRUCTURE).first_seen_at
            seen[structure.type_id] = StructureObservation(
                count_seen=len(tags),
                first_seen_at=now if first_seen is None else first_seen,
                last_seen_at=now,
            )
        return tuple(sorted(seen.items(), key=lambda item: item[0].name))

    def _counted(self, tags: set[int], attention: AttentionState, *, worker: bool) -> int:
        for unit in attention.enemy_units:
            if unit.is_worker == worker and (worker or is_army(unit)):
                tags.add(unit.tag)
        return len(tags)

    def _coverage(self, attention: AttentionState) -> float:
        grid = attention.visibility
        if grid is None or not len(self._main_seen):
            return self.observations.main_scout_coverage
        inside = (self._main_ys < grid.shape[0]) & (self._main_xs < grid.shape[1])
        visible = np.zeros(len(self._main_seen), dtype=bool)
        visible[inside] = grid[self._main_ys[inside], self._main_xs[inside]] == 2
        self._main_seen |= visible
        return float(self._main_seen.mean())

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from sc2.ids.unit_typeid import UnitTypeId


@dataclass(frozen=True, slots=True)
class ReferenceBuildPoint:
    """Cumulative structure counts a standard build has reached by ``time``.

    A point only needs to list the types that changed since the previous
    one; ``ReferenceBuild.target_for`` carries the last known value forward
    for anything not repeated.
    """

    time: float
    counts: Mapping[UnitTypeId, int]

    def __post_init__(self) -> None:
        if self.time < 0.0:
            raise ValueError("reference build point time must not be negative")
        for count in self.counts.values():
            if count < 0:
                raise ValueError("reference build counts must not be negative")
        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts)))


@dataclass(frozen=True, slots=True)
class ReferenceBuild:
    """A named, time-ordered macro benchmark sourced from a standard build.

    Not a schedule the bot is forced to follow: ``MacroPlanner`` uses it only
    as a floor -- "a standard build would have this many of X by now" -- on
    top of its own income-driven and bank-overflow-driven targets (see
    ``ResourceOverflowConfig`` in ``bot.macro.strategy.config``). Past the
    last point the floor holds steady; nothing in the sources below claims a
    "standard" building count for an open-ended macro game, so growth beyond
    that point is left to those other two signals rather than invented here.
    """

    name: str
    source: str
    points: tuple[ReferenceBuildPoint, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("reference build name must not be empty")
        if not self.source.strip():
            raise ValueError("reference build source must not be empty")
        times = [point.time for point in self.points]
        if times != sorted(times):
            raise ValueError("reference build points must be sorted by time")

    def target_for(self, structure_type: UnitTypeId, now: float) -> int:
        """Return the benchmark count a standard build has by ``now``."""

        target = 0
        for point in self.points:
            if point.time > now:
                break
            if structure_type in point.counts:
                target = point.counts[structure_type]
        return target


def bio_three_one_one_reference() -> ReferenceBuild:
    """Standard TvX bio 3-1-1 production-structure benchmark.

    Timings blend a recorded TvP "3-rax macro opening" (Spawning Tool build
    98237: 15 Barracks @0:41, 20 2nd Barracks @1:51, 22 3rd Barracks @2:17,
    52 Factory @4:34, 50 Starport @6:12) with the qualitative sequencing from
    terrancraft's "TvP Standard 3-1-1 Framework" article -- both already
    informed this bot's own opening (see ``terran_builds.yml`` and
    ``_botdev/architecture/opening.md``). Only production structures are
    tracked, since only ``construction.capacity`` consults this;
    imprecision here is not load-bearing, as it only ever raises a floor
    that the existing income/overflow scaling would otherwise reach anyway.
    """

    return ReferenceBuild(
        name="bio_three_one_one",
        source=(
            "lotv.spawningtool.com/build/98237 "
            "(TvP 3-rax Macro Opening) + "
            "terrancraft.com/2020/01/21/tvp-standard-3-1-1-framework"
        ),
        points=(
            ReferenceBuildPoint(
                0.0,
                {
                    UnitTypeId.BARRACKS: 0,
                    UnitTypeId.FACTORY: 0,
                    UnitTypeId.STARPORT: 0,
                },
            ),
            ReferenceBuildPoint(41.0, {UnitTypeId.BARRACKS: 1}),
            ReferenceBuildPoint(111.0, {UnitTypeId.BARRACKS: 2}),
            ReferenceBuildPoint(137.0, {UnitTypeId.BARRACKS: 3}),
            ReferenceBuildPoint(274.0, {UnitTypeId.FACTORY: 1}),
            ReferenceBuildPoint(372.0, {UnitTypeId.STARPORT: 1}),
        ),
    )

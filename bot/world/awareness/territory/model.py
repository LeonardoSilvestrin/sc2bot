"""Types of the territory reading: who holds each place, and how exposed it is.

Control, value and security stay apart. A reading says who dominates a place;
how much the place matters (chokes, routes) stays on ``SpatialField``; how
reachable it is to enemy ground forces is ``ground_access``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum, auto

from sc2.position import Point2

from ..spatial.kernel import distance_squared

# A townhall stands on its expansion slot; this absorbs the rounding between
# the two (the tolerance ``WorldFacts.bases`` uses to recognise the main).
_SLOT_TOLERANCE = 3.0


class TerritoryControl(Enum):
    """Who holds a place, as Awareness perceives it."""

    FRIENDLY = auto()
    CONTESTED = auto()
    ENEMY = auto()
    # Nobody's influence is significant here. Not the same as disputed.
    UNCONTROLLED = auto()


@dataclass(frozen=True, slots=True)
class FriendlyForce:
    """One friendly cluster already used to calculate territorial influence."""

    center: Point2
    radius: float
    combat_strength: float
    anti_ground_strength: float
    unit_count: int
    position_uncertainty: float = 0.0
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class TerritoryReading:
    """Both sides' influence at one place, and who that says holds it.

    ``friendly_influence`` and ``enemy_influence`` are saturated (0..1), each
    side's army and bases together. Of ours, ``friendly_military`` is the army
    alone and ``friendly_ground_denial`` the part of it that can fight ground
    units. ``dominance`` is the normalized difference, -1 (enemy) to +1 (ours).

    ``confidence`` is how well we know the enemy side of the reading -- ours is
    always known. It rests on how recently we looked at the place and on how
    current the enemy sources reaching it are, never on the mere absence of
    known enemies: unwatched empty space is UNCONTROLLED at confidence 0.
    """

    friendly_influence: float = 0.0
    enemy_influence: float = 0.0
    dominance: float = 0.0
    control: TerritoryControl = TerritoryControl.UNCONTROLLED
    confidence: float = 0.0
    friendly_military: float = 0.0
    friendly_ground_denial: float = 0.0

    @property
    def presence(self) -> float:
        """Both sides' influence together, saturated like either one."""

        return 1.0 - (1.0 - self.friendly_influence) * (1.0 - self.enemy_influence)

    @property
    def hold(self) -> float:
        """How firmly we hold the place against ground passage, 0..1.

        Our ground-capable army's influence where we dominate; nothing where
        the place is contested or the enemy's. A base makes a place ours but
        stops no one, and neither does a unit that only shoots air.
        """

        return self.friendly_ground_denial * max(0.0, self.dominance)


@dataclass(frozen=True, slots=True)
class TerritorySample:
    """The reading at one sample of the spatial lattice."""

    position: Point2
    reading: TerritoryReading
    region: str | None = None

    @property
    def control(self) -> TerritoryControl:
        return self.reading.control


@dataclass(frozen=True, slots=True)
class RegionTerritory:
    """One ground region: who holds it, and how exposed it is by ground.

    ``ground_access`` is 1.0 where an enemy ground force walks in freely and
    0.0 where every way in is firmly held. Only passages are barriers: a
    region says who holds it, a passage how blocked the way through is, so
    one army is not counted once for every node its influence reaches. The
    region's own control never shields it.
    """

    key: str
    center: Point2
    expansions: tuple[Point2, ...]
    reading: TerritoryReading
    ground_access: float = 1.0
    # Shadow comparison, to drop once matches decide between the two: the
    # same walk with regions acting as barriers too (the first model). Never
    # above ``ground_access``.
    layered_ground_access: float = 1.0

    @property
    def control(self) -> TerritoryControl:
        return self.reading.control

    @property
    def ground_security(self) -> float:
        return 1.0 - self.ground_access


@dataclass(frozen=True, slots=True)
class PassageTerritory:
    """The reading where one ground passage joins two regions."""

    key: str
    position: Point2
    regions: tuple[str, str]
    reading: TerritoryReading

    @property
    def control(self) -> TerritoryControl:
        return self.reading.control


@dataclass(frozen=True, slots=True)
class BaseTerritory:
    """One of our bases, placed in its region (``None``: no region graph)."""

    base_id: str
    position: Point2
    region: RegionTerritory | None


@dataclass(frozen=True, slots=True)
class TerritorySnapshot:
    """The perceived state of the map's territory.

    It describes and never prescribes: where each side holds the map, where
    they meet, and how exposed each region is to enemy ground forces.
    """

    samples: tuple[TerritorySample, ...] = field(default_factory=tuple)
    regions: tuple[RegionTerritory, ...] = field(default_factory=tuple)
    passages: tuple[PassageTerritory, ...] = field(default_factory=tuple)
    bases: tuple[BaseTerritory, ...] = field(default_factory=tuple)
    # Exact friendly clusters consumed by this territory update. Keeping
    # them on the immutable snapshot lets diagnostics display the calculation
    # inputs without clustering the units a second time.
    friendly_forces: tuple[FriendlyForce, ...] = field(default_factory=tuple)
    # Approximate points where friendly and enemy dominance meet.
    frontline: tuple[Point2, ...] = field(default_factory=tuple)
    # Mean sample confidence: how much of the map we currently know.
    confidence: float = 0.0
    updated_at: float = 0.0

    def region(self, key: str) -> RegionTerritory | None:
        return next((item for item in self.regions if item.key == key), None)

    def region_at(self, position: Point2) -> RegionTerritory | None:
        key = locate_region(
            position,
            slots=(
                (expansion, region.key)
                for region in self.regions
                for expansion in region.expansions
            ),
            samples=((sample.position, sample.region) for sample in self.samples),
        )
        return None if key is None else self.region(key)

    def at(self, position: Point2) -> TerritorySample | None:
        """The reading at the sample nearest to ``position``."""

        return min(
            self.samples,
            key=lambda sample: distance_squared(sample.position, position),
            default=None,
        )

    def count(self, control: TerritoryControl) -> int:
        return sum(sample.control is control for sample in self.samples)


def locate_region(
    position: Point2,
    *,
    slots: Iterable[tuple[Point2, str]],
    samples: Iterable[tuple[Point2, str | None]],
) -> str | None:
    """The key of the region ``position`` lies in.

    An expansion slot under the position names its region outright;
    otherwise it is the region of the nearest sample that has one.
    """

    slot = min(
        slots, key=lambda item: distance_squared(position, item[0]), default=None
    )
    if slot is not None and distance_squared(position, slot[0]) <= _SLOT_TOLERANCE**2:
        return slot[1]
    nearest: tuple[Point2, str] | None = None
    nearest_distance = 0.0
    for point, region in samples:
        if region is None:
            continue
        distance = distance_squared(position, point)
        if nearest is None or distance < nearest_distance:
            nearest, nearest_distance = (point, region), distance
    return None if nearest is None else nearest[1]

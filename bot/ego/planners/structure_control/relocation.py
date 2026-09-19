"""Relocation: a Siege Tank walled in by our own production, and the one
structure lifted out of its way.

A Tank is stuck when it has an order to walk to a point more than
`arrive_distance` away and has stayed within `progress_distance` of one spot
for `stuck_after` seconds. A Tank with no such order (idle, or waiting at its
point), sieged, or with a visible enemy within `combat_reach` is not tracked at
all. One seen without an order for up to `order_grace` seconds keeps its track:
the game drops an order it cannot path, and the behavior gives it again.

Its blocker is a landed Barracks, Factory or Starport whose footprint lies
within `blocker_reach` of the Tank's next `look_ahead` cells toward its point,
with its centre ahead of the Tank. One without an add-on goes first -- lifting
leaves the add-on behind -- then the one closest to that way. Command Centers
never move.

One relocation at a time: lift the blocker; once it flies, wait until the Tank
has covered `progress_distance` from where it was stuck (or is gone, or
`wait_timeout` passed); then land it on the nearest free production site of the
main whose footprint keeps `lane` cells from the Tank's way and from the ramp
corridor. With no such site it stays in the air and looks again every
`land_retry` seconds; a site not landed on within `land_timeout` is dropped for
the next one. Once a relocation ends no other starts for `global_cooldown`
seconds, and a structure is not lifted again for `structure_cooldown` seconds
after its lift.

The ramp corridor is the band `lane` cells either side of the segment from our
start to the top of the main ramp. Nothing lands in it and, through the Body,
Ares builds no production in it either.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, MapView, UnitView
from bot.ego.planners import RelocationEvent

TANK = UnitTypeId.SIEGETANK
MOBILE = frozenset({UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT})
# Half the side of a production structure, and where its add-on sits.
PRODUCTION_HALF_SIDE = 1.5
ADD_ON_OFFSET = Point2((2.5, -0.5))
ADD_ON_HALF_SIDE = 1.0
# Half the side of the structures that are not 3x3; any other counts as 3x3.
HALF_SIDE: dict[UnitTypeId, float] = {
    **dict.fromkeys(
        (
            UnitTypeId.COMMANDCENTER,
            UnitTypeId.ORBITALCOMMAND,
            UnitTypeId.PLANETARYFORTRESS,
            UnitTypeId.NEXUS,
            UnitTypeId.HATCHERY,
            UnitTypeId.LAIR,
            UnitTypeId.HIVE,
        ),
        2.5,
    ),
    **dict.fromkeys(
        (
            UnitTypeId.SUPPLYDEPOT,
            UnitTypeId.SUPPLYDEPOTLOWERED,
            UnitTypeId.MISSILETURRET,
            UnitTypeId.BARRACKSREACTOR,
            UnitTypeId.BARRACKSTECHLAB,
            UnitTypeId.FACTORYREACTOR,
            UnitTypeId.FACTORYTECHLAB,
            UnitTypeId.STARPORTREACTOR,
            UnitTypeId.STARPORTTECHLAB,
            UnitTypeId.PYLON,
            UnitTypeId.PHOTONCANNON,
        ),
        1.0,
    ),
    UnitTypeId.SENSORTOWER: 0.5,
}
# Ares lands a structure once it flies this close to its site.
LANDING_REACH = 5.5
# Boxes that share only an edge do not overlap.
_EDGE = 0.01

LIFTING = "lifting"
WAITING = "waiting"
LANDING = "landing"

Box = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class RelocationConfig:
    # A Tank that stays within this many cells of one spot makes no progress.
    progress_distance: float = 1.5
    # Seconds without progress, ordered to walk, before a Tank is stuck.
    stuck_after: float = 4.0
    # An order to a point this close is a Tank at its point, not walking.
    arrive_distance: float = 3.0
    # A Tank with a visible enemy this close is fighting, not stuck.
    combat_reach: float = 12.0
    # Seconds a Tank seen without an order keeps its track.
    order_grace: float = 1.0
    # The Tank's way a blocker is looked for on, in cells ahead of it ...
    look_ahead: float = 4.0
    # ... and how close to that way a blocker's footprint must be.
    blocker_reach: float = 1.5
    # Seconds a lift may take before the relocation is given up.
    lift_timeout: float = 6.0
    # Seconds a lifted structure waits for the Tank before it lands anyway.
    wait_timeout: float = 8.0
    # Cells a landing site's footprint keeps from the Tank's way and the ramp corridor.
    lane: float = 2.5
    # Seconds to land on a site before the next one is tried.
    land_timeout: float = 25.0
    # Seconds between searches that found no landing site.
    land_retry: float = 5.0
    # Seconds after a relocation ends before another may start.
    global_cooldown: float = 20.0
    # Seconds after a structure's lift before it may be lifted again.
    structure_cooldown: float = 90.0

    def __post_init__(self) -> None:
        for name in (
            "progress_distance",
            "stuck_after",
            "arrive_distance",
            "look_ahead",
            "lift_timeout",
            "wait_timeout",
            "land_timeout",
            "land_retry",
        ):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        for name in (
            "combat_reach",
            "order_grace",
            "blocker_reach",
            "lane",
            "global_cooldown",
            "structure_cooldown",
        ):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class RelocationStep:
    lift: tuple[int, ...] = ()
    land: tuple[tuple[int, Point2], ...] = ()
    events: tuple[RelocationEvent, ...] = ()


@dataclass(slots=True)
class _Track:
    # Where the Tank last made progress, and when.
    anchor: Point2
    since: float
    # The last frame it had an order to walk, and to where.
    ordered_at: float
    destination: Point2
    announced: bool = False


@dataclass(slots=True)
class _Relocation:
    structure: int
    tank: int
    started: float
    origin: Point2
    # Where the Tank was stuck, and the point it was walking to.
    tank_at: Point2
    destination: Point2
    phase: str
    since: float
    site: Point2 | None = None
    site_since: float = 0.0
    retry_at: float = 0.0
    failed: set[Point2] = field(default_factory=set)
    announced_landing: bool = False
    announced_no_site: bool = False


class Relocator:
    def __init__(self, config: RelocationConfig | None = None) -> None:
        self.config = config or RelocationConfig()
        self._tracks: dict[int, _Track] = {}
        self._active: _Relocation | None = None
        # No relocation starts before this time.
        self._ready_at = -math.inf
        # When each structure was last lifted, by tag.
        self._lifted_at: dict[int, float] = {}

    def corridor(self, map_view: MapView) -> tuple[Point2, ...]:
        """The production sites of the main inside the ramp corridor."""

        way = (map_view.own_start, map_view.main_ramp)
        return tuple(
            site
            for site in map_view.production_sites
            if _near_way(_site_boxes(site), (way,), self.config.lane)
        )

    def plan(self, attention: AttentionState) -> RelocationStep:
        now = attention.time
        tanks = {unit.tag: unit for unit in attention.own_units if unit.type_id is TANK}
        newly_stuck = self._track(attention, tanks)
        events: list[RelocationEvent] = []
        lift: tuple[int, ...] = ()
        land: tuple[tuple[int, Point2], ...] = ()
        started_for: int | None = None
        if self._active is not None:
            land = self._advance(attention, tanks, events)
            blocked = "relocation_active"
        elif now < self._ready_at:
            blocked = "cooldown"
        else:
            blocked = "no_blocker"
            events = self._start(attention, tanks)
            if self._active is not None:
                started_for, lift = self._active.tank, (self._active.structure,)
                blocked = "relocation_active"
        stuck_events = [
            RelocationEvent(
                transition="tank_stuck",
                reason="blocker_selected" if tag == started_for else blocked,
                tank=tag,
                inputs=self._stuck_inputs(tanks[tag], now),
            )
            for tag in newly_stuck
        ]
        return RelocationStep(lift=lift, land=land, events=(*stuck_events, *events))

    def _track(self, attention: AttentionState, tanks: dict[int, UnitView]) -> list[int]:
        """Updates the Tanks' progress; returns those stuck from this frame on."""

        config = self.config
        now = attention.time
        threats = [
            enemy.position
            for enemy in attention.enemy_units
            if not enemy.is_flying or enemy.can_attack_ground
        ]
        tracks: dict[int, _Track] = {}
        newly: list[int] = []
        for tag, tank in tanks.items():
            position = tank.position
            if any(position.distance_to(enemy) <= config.combat_reach for enemy in threats):
                continue
            track = self._tracks.get(tag)
            if track is not None and position.distance_to(track.anchor) > config.progress_distance:
                # It got somewhere: whatever held it has let it go.
                track = None
            target = tank.moving_to
            if target is not None and position.distance_to(target) > config.arrive_distance:
                if track is None:
                    track = _Track(position, now, now, target)
                else:
                    track.ordered_at, track.destination = now, target
            elif track is None or now - track.ordered_at > config.order_grace:
                continue
            tracks[tag] = track
            if not track.announced and now - track.since >= config.stuck_after:
                track.announced = True
                newly.append(tag)
        self._tracks = tracks
        return sorted(newly)

    def _stuck(self, now: float) -> list[int]:
        """The stuck Tanks, longest stuck first."""

        stuck = [
            (track.since, tag)
            for tag, track in self._tracks.items()
            if now - track.since >= self.config.stuck_after
        ]
        return [tag for _, tag in sorted(stuck)]

    def _stuck_inputs(self, tank: UnitView, now: float) -> tuple[tuple[str, float], ...]:
        track = self._tracks[tank.tag]
        return (
            ("stuck_for", now - track.since),
            ("moved", tank.position.distance_to(track.anchor)),
            ("destination_distance", tank.position.distance_to(track.destination)),
        )

    def _start(
        self, attention: AttentionState, tanks: dict[int, UnitView]
    ) -> list[RelocationEvent]:
        """Lifts the blocker of the Tank stuck longest that has one."""

        now = attention.time
        for tag in self._stuck(now):
            tank = tanks[tag]
            track = self._tracks[tag]
            chosen = self._blocker(attention, tank, track.destination)
            if chosen is None:
                continue
            blocker, gap, candidates = chosen
            self._active = _Relocation(
                structure=blocker.tag,
                tank=tag,
                started=now,
                origin=blocker.position,
                tank_at=tank.position,
                destination=track.destination,
                phase=LIFTING,
                since=now,
            )
            self._lifted_at = {
                key: at
                for key, at in self._lifted_at.items()
                if now - at < self.config.structure_cooldown
            }
            self._lifted_at[blocker.tag] = now
            return [
                RelocationEvent(
                    transition="blocker_selected",
                    reason="with_add_on" if blocker.has_add_on else "no_add_on",
                    tank=tag,
                    structure=blocker.tag,
                    site=blocker.position,
                    inputs=(
                        ("gap", gap),
                        ("candidates", float(candidates)),
                        ("has_add_on", float(blocker.has_add_on)),
                    ),
                ),
                RelocationEvent(
                    transition="lifting",
                    reason="lift_ordered",
                    tank=tag,
                    structure=blocker.tag,
                    site=blocker.position,
                ),
            ]
        return []

    def _blocker(
        self, attention: AttentionState, tank: UnitView, destination: Point2
    ) -> tuple[UnitView, float, int] | None:
        """The structure to lift for `tank`, how far it is from the Tank's
        way, and how many could have been lifted."""

        config = self.config
        now = attention.time
        heading = destination - tank.position
        length = math.hypot(heading.x, heading.y)
        if length == 0.0:
            return None
        direction = heading / length
        way = (tank.position, tank.position + direction * config.look_ahead)
        candidates: list[tuple[bool, float, int, UnitView]] = []
        for structure in attention.own_structures:
            if (
                structure.type_id not in MOBILE
                or not structure.is_ready
                or now - self._lifted_at.get(structure.tag, -math.inf) < config.structure_cooldown
            ):
                continue
            offset = structure.position - tank.position
            if offset.x * direction.x + offset.y * direction.y <= 0.0:
                continue
            gap = _gap(*way, _square(structure.position, PRODUCTION_HALF_SIDE))
            if gap <= config.blocker_reach:
                candidates.append((structure.has_add_on, gap, structure.tag, structure))
        if not candidates:
            return None
        _, gap, _, blocker = min(candidates, key=lambda item: item[:3])
        return blocker, gap, len(candidates)

    def _advance(
        self,
        attention: AttentionState,
        tanks: dict[int, UnitView],
        events: list[RelocationEvent],
    ) -> tuple[tuple[int, Point2], ...]:
        config = self.config
        now = attention.time
        relocation = self._active
        assert relocation is not None
        structure = next(
            (item for item in attention.own_structures if item.tag == relocation.structure),
            None,
        )
        if structure is None:
            self._end(now, events, "relocation_aborted", "structure_lost")
            return ()
        if relocation.phase == LIFTING:
            if not structure.is_flying:
                if now - relocation.since > config.lift_timeout:
                    self._end(now, events, "relocation_aborted", "lift_failed")
                return ()
            relocation.phase, relocation.since = WAITING, now
        if relocation.phase == WAITING:
            # Dead or sieged, it is not walking any more.
            tank = tanks.get(relocation.tank)
            moved = None if tank is None else tank.position.distance_to(relocation.tank_at)
            if moved is None:
                transition = "tank_gone"
            elif moved > config.progress_distance:
                transition = "tank_moving"
            elif now - relocation.since >= config.wait_timeout:
                transition = "tank_still_stuck"
            else:
                return ()
            inputs = (("waited", now - relocation.since),)
            if moved is not None:
                inputs += (("moved", moved),)
            events.append(self._event(transition, "land_after", None, inputs))
            relocation.phase, relocation.since, relocation.retry_at = LANDING, now, now
        if not structure.is_flying:
            self._end(now, events, "relocation_complete", "landed", site=structure.position)
            return ()
        if relocation.site is not None:
            if (
                not relocation.announced_landing
                and structure.position.distance_to(relocation.site) <= LANDING_REACH
            ):
                relocation.announced_landing = True
                events.append(self._event("landing", "at_site", relocation.site))
            if now - relocation.site_since <= config.land_timeout:
                return ()
            relocation.failed.add(relocation.site)
            relocation.site, relocation.announced_landing = None, False
            relocation.retry_at = now
        if now < relocation.retry_at:
            return ()
        site, free = self._landing_site(attention, relocation)
        if site is None:
            relocation.retry_at = now + config.land_retry
            if not relocation.announced_no_site:
                relocation.announced_no_site = True
                events.append(
                    self._event(
                        "no_landing_site",
                        "keep_flying",
                        None,
                        (("sites", float(len(attention.map.production_sites))),),
                    )
                )
            return ()
        relocation.site, relocation.site_since = site, now
        events.append(
            self._event(
                "relocating",
                "retry" if relocation.failed else "site_found",
                site,
                (
                    ("free_sites", float(free)),
                    ("flight", structure.position.distance_to(site)),
                ),
            )
        )
        return ((relocation.structure, site),)

    def _landing_site(
        self, attention: AttentionState, relocation: _Relocation
    ) -> tuple[Point2 | None, int]:
        """The free site nearest the origin, off the Tank's way and the ramp
        corridor, and how many free sites there were."""

        lane = self.config.lane
        map_view = attention.map
        taken = [
            _square(structure.position, HALF_SIDE.get(structure.type_id, PRODUCTION_HALF_SIDE))
            for structure in (*attention.own_structures, *attention.enemy_structures)
            if not structure.is_flying and structure.tag != relocation.structure
        ]
        ways = (
            (relocation.tank_at, relocation.destination),
            (map_view.own_start, map_view.main_ramp),
        )
        free: list[tuple[float, float, float, Point2]] = []
        for site in map_view.production_sites:
            if site in relocation.failed or site.distance_to(relocation.origin) < 1.0:
                continue
            boxes = _site_boxes(site)
            if any(_overlap(box, other) for box in boxes for other in taken):
                continue
            if _near_way(boxes, ways, lane):
                continue
            free.append((site.distance_to(relocation.origin), site.x, site.y, site))
        if not free:
            return None, 0
        return min(free)[-1], len(free)

    def _end(
        self,
        now: float,
        events: list[RelocationEvent],
        transition: str,
        reason: str,
        *,
        site: Point2 | None = None,
    ) -> None:
        relocation = self._active
        assert relocation is not None
        events.append(
            self._event(transition, reason, site, (("took", now - relocation.started),))
        )
        self._active = None
        self._ready_at = now + self.config.global_cooldown

    def _event(
        self,
        transition: str,
        reason: str,
        site: Point2 | None,
        inputs: tuple[tuple[str, float], ...] = (),
    ) -> RelocationEvent:
        relocation = self._active
        assert relocation is not None
        return RelocationEvent(
            transition=transition,
            reason=reason,
            tank=relocation.tank,
            structure=relocation.structure,
            site=site,
            inputs=inputs,
        )


def _site_boxes(site: Point2) -> tuple[Box, Box]:
    """A production structure on `site` and its add-on."""

    return (
        _square(site, PRODUCTION_HALF_SIDE),
        _square(site + ADD_ON_OFFSET, ADD_ON_HALF_SIDE),
    )


def _near_way(
    boxes: tuple[Box, ...], ways: tuple[tuple[Point2, Point2], ...], lane: float
) -> bool:
    return any(_gap(start, end, box) < lane for start, end in ways for box in boxes)


def _square(center: Point2, half: float) -> Box:
    return (center.x - half, center.y - half, center.x + half, center.y + half)


def _overlap(first: Box, second: Box) -> bool:
    return (
        first[0] < second[2] - _EDGE
        and second[0] < first[2] - _EDGE
        and first[1] < second[3] - _EDGE
        and second[1] < first[3] - _EDGE
    )


def _gap(start: Point2, end: Point2, box: Box) -> float:
    """Distance from the segment `start`-`end` to `box`; 0 where they meet.

    Apart, the closest pair has an end of the segment or a corner of the box.
    """

    if _crosses(start, end, box):
        return 0.0
    min_x, min_y, max_x, max_y = box
    corners = (
        Point2((min_x, min_y)),
        Point2((min_x, max_y)),
        Point2((max_x, min_y)),
        Point2((max_x, max_y)),
    )
    return min(
        _box_distance(start, box),
        _box_distance(end, box),
        *(_segment_distance(corner, start, end) for corner in corners),
    )


def _crosses(start: Point2, end: Point2, box: Box) -> bool:
    """Liang-Barsky: whether any part of the segment lies in the box."""

    low, high = 0.0, 1.0
    dx, dy = end.x - start.x, end.y - start.y
    for step, room in (
        (-dx, start.x - box[0]),
        (dx, box[2] - start.x),
        (-dy, start.y - box[1]),
        (dy, box[3] - start.y),
    ):
        if step == 0.0:
            if room < 0.0:
                return False
            continue
        bound = room / step
        if step < 0.0:
            low = max(low, bound)
        else:
            high = min(high, bound)
        if low > high:
            return False
    return True


def _box_distance(point: Point2, box: Box) -> float:
    dx = max(box[0] - point.x, 0.0, point.x - box[2])
    dy = max(box[1] - point.y, 0.0, point.y - box[3])
    return math.hypot(dx, dy)


def _segment_distance(point: Point2, start: Point2, end: Point2) -> float:
    dx, dy = end.x - start.x, end.y - start.y
    length = dx * dx + dy * dy
    if length == 0.0:
        return point.distance_to(start)
    t = max(0.0, min(1.0, ((point.x - start.x) * dx + (point.y - start.y) * dy) / length))
    return point.distance_to(Point2((start.x + t * dx, start.y + t * dy)))

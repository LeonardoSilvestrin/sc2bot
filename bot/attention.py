"""ATTENTION: what the bot perceives this frame, before any interpretation.

`observe` reads Ares/python-sc2 once per frame and returns an immutable
`AttentionState`; every later layer reads that state instead of the bot. The
static map (`MapView`) is read once per game by `read_map`.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.map_topology import MapTopology, build_topology

WORKER_TYPES = frozenset(
    {UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.MULE}
)
# sqrt(dps * hit points) of a Marine: `UnitView.power` is counted in Marines.
MARINE_POWER = math.sqrt(9.8 * 45.0)
# A townhall this close to an expansion location is that base.
_BASE_SNAP_DISTANCE = 6.0


@dataclass(frozen=True, slots=True)
class UnitView:
    tag: int
    type_id: UnitTypeId
    position: Point2
    # (health + shield) / (max health + max shield)
    health: float
    power: float
    supply: float
    is_flying: bool
    can_attack_ground: bool
    can_attack_air: bool
    is_worker: bool
    is_structure: bool
    is_ready: bool = True
    # The Ares role the unit holds, by name; None without one.
    role: str | None = None


@dataclass(frozen=True, slots=True)
class BaseView:
    base_id: str
    position: Point2
    is_main: bool


@dataclass(frozen=True, slots=True)
class MapView:
    name: str
    # Playable area: min x, min y, max x, max y.
    bounds: tuple[float, float, float, float]
    own_start: Point2
    enemy_start: Point2
    main_ramp: Point2
    expansions: tuple[Point2, ...]
    # Pathable points on a regular grid, row by row.
    lattice: tuple[Point2, ...]
    lattice_spacing: float
    topology: MapTopology = field(default_factory=MapTopology)


@dataclass(frozen=True, slots=True)
class AttentionState:
    iteration: int
    time: float
    minerals: int
    vespene: int
    supply_used: float
    supply_cap: float
    workers: int
    opening: str
    opening_done: bool
    own_units: tuple[UnitView, ...]
    own_structures: tuple[UnitView, ...]
    enemy_units: tuple[UnitView, ...]
    enemy_structures: tuple[UnitView, ...]
    bases: tuple[BaseView, ...]
    dead_tags: frozenset[int]
    map: MapView
    # python-sc2 visibility indexed [y, x]; 2 means in vision now. Left out of
    # equality: two frames that perceived the same units are the same frame.
    visibility: np.ndarray | None = field(default=None, compare=False, repr=False)

    def is_visible(self, point: Point2) -> bool:
        grid = self.visibility
        if grid is None:
            return False
        x, y = int(point.x), int(point.y)
        return 0 <= y < grid.shape[0] and 0 <= x < grid.shape[1] and grid[y, x] == 2


def unit_power(dps: float, hit_points: float) -> float:
    """Lanchester-style fighting value, sqrt(dps * hit points), in Marines."""

    return math.sqrt(max(0.0, dps) * max(0.0, hit_points)) / MARINE_POWER


def read_map(bot, *, lattice_spacing: int = 4) -> MapView:
    if lattice_spacing <= 0:
        raise ValueError("lattice_spacing must be positive")
    info = bot.game_info
    area = info.playable_area
    bounds = (
        float(area.x),
        float(area.y),
        float(area.x + area.width),
        float(area.y + area.height),
    )
    own_start = _point(bot.start_location)
    enemy_start = _point(bot.enemy_start_locations[0])
    try:
        main_ramp = _point(bot.main_base_ramp.top_center)
    except (AttributeError, IndexError, ValueError):
        main_ramp = own_start
    expansions = tuple(
        sorted(
            {_point(location) for location in bot.expansion_locations_list},
            key=lambda point: (point.x, point.y),
        )
    )
    pathing = np.asarray(info.pathing_grid.data_numpy)
    lattice = pathable_lattice(pathing, lattice_spacing, bounds)
    topology = build_topology(
        pathing,
        lattice,
        float(lattice_spacing),
        expansions,
        own_start,
        enemy_start,
        map_data=_map_data(bot),
    )
    return MapView(
        name=str(info.map_name),
        bounds=bounds,
        own_start=own_start,
        enemy_start=enemy_start,
        main_ramp=main_ramp,
        expansions=expansions,
        lattice=lattice,
        lattice_spacing=float(lattice_spacing),
        topology=topology,
    )


def pathable_lattice(
    grid: np.ndarray, spacing: int, bounds: tuple[float, float, float, float]
) -> tuple[Point2, ...]:
    """Pathable cell centres every ``spacing`` cells, in row-major order."""

    offset = spacing // 2
    rows, columns = np.nonzero(grid[offset::spacing, offset::spacing])
    min_x, min_y, max_x, max_y = bounds
    points: list[Point2] = []
    for row, column in zip(rows.tolist(), columns.tolist(), strict=True):
        x = column * spacing + offset + 0.5
        y = row * spacing + offset + 0.5
        if min_x <= x <= max_x and min_y <= y <= max_y:
            points.append(Point2((x, y)))
    return tuple(points)


def observe(bot, iteration: int, map_view: MapView) -> AttentionState:
    supply = _supply_lookup(bot)
    roles = _roles(bot)
    runner = getattr(bot, "build_order_runner", None)
    state = bot.state
    return AttentionState(
        iteration=int(iteration),
        time=float(bot.time),
        minerals=int(bot.minerals),
        vespene=int(bot.vespene),
        supply_used=float(bot.supply_used),
        supply_cap=float(bot.supply_cap),
        workers=sum(
            1
            for unit in bot.units
            if unit.type_id in WORKER_TYPES and unit.type_id is not UnitTypeId.MULE
        ),
        opening=str(getattr(runner, "chosen_opening", "") or ""),
        opening_done=bool(getattr(runner, "build_completed", True)),
        own_units=_views(bot.units, supply, roles),
        own_structures=_views(bot.structures, supply, roles),
        enemy_units=_views(_visible(bot.enemy_units), supply),
        enemy_structures=_views(_visible(bot.enemy_structures), supply),
        bases=_bases(bot.townhalls, map_view),
        dead_tags=frozenset(int(tag) for tag in getattr(state, "dead_units", ())),
        map=map_view,
        visibility=getattr(getattr(state, "visibility", None), "data_numpy", None),
    )


def unit_view(
    unit,
    supply: Callable[[UnitTypeId], float],
    roles: Mapping[int, str] | None = None,
) -> UnitView:
    hit_points = float(unit.health) + float(unit.shield)
    max_hit_points = float(unit.health_max) + float(unit.shield_max)
    return UnitView(
        tag=int(unit.tag),
        type_id=unit.type_id,
        position=_point(unit.position),
        health=hit_points / max_hit_points if max_hit_points > 0.0 else 0.0,
        power=unit_power(max(float(unit.ground_dps), float(unit.air_dps)), hit_points),
        supply=supply(unit.type_id),
        is_flying=bool(unit.is_flying),
        can_attack_ground=bool(unit.can_attack_ground),
        can_attack_air=bool(unit.can_attack_air),
        is_worker=unit.type_id in WORKER_TYPES,
        is_structure=bool(unit.is_structure),
        is_ready=bool(unit.is_ready),
        role=None if roles is None else roles.get(int(unit.tag)),
    )


def _views(
    units: Iterable,
    supply: Callable[[UnitTypeId], float],
    roles: Mapping[int, str] | None = None,
) -> tuple[UnitView, ...]:
    return tuple(
        sorted((unit_view(unit, supply, roles) for unit in units), key=lambda v: v.tag)
    )


def _roles(bot) -> dict[int, str]:
    """Ares' role of every unit that has one, by tag."""

    try:
        by_role = bot.mediator.get_unit_role_dict
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return {}
    return {
        int(tag): str(getattr(role, "name", role))
        for role, tags in by_role.items()
        for tag in tags
    }


def _visible(units: Iterable) -> Iterable:
    return (unit for unit in units if getattr(unit, "is_visible", True))


def _supply_lookup(bot) -> Callable[[UnitTypeId], float]:
    cache: dict[UnitTypeId, float] = {}

    def supply(type_id: UnitTypeId) -> float:
        if type_id not in cache:
            try:
                cache[type_id] = float(bot.calculate_supply_cost(type_id))
            except (AttributeError, KeyError, TypeError):
                cache[type_id] = 0.0
        return cache[type_id]

    return supply


def _bases(townhalls: Iterable, map_view: MapView) -> tuple[BaseView, ...]:
    bases: dict[str, BaseView] = {}
    for townhall in townhalls:
        if townhall.is_flying:
            continue
        position = _point(townhall.position)
        anchor = min(
            map_view.expansions,
            key=lambda point: (point.distance_to(position), point.x, point.y),
            default=position,
        )
        if anchor.distance_to(position) > _BASE_SNAP_DISTANCE:
            anchor = position
        base_id = f"base:{round(anchor.x)}:{round(anchor.y)}"
        bases[base_id] = BaseView(
            base_id=base_id,
            position=anchor,
            is_main=anchor.distance_to(map_view.own_start) <= _BASE_SNAP_DISTANCE,
        )
    return tuple(bases[key] for key in sorted(bases))


def _point(value) -> Point2:
    return Point2((float(value[0]), float(value[1])))


def _map_data(bot):
    try:
        return bot.mediator.get_map_data_object
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return None

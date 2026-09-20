"""The static map: read once per game, in ``on_start``, and frozen.

`read_map` reads what the physical map is -- playable area, starts, main ramp,
expansions, a pathable lattice and its `MapTopology` (regions, passages,
adjacency), and where a production structure fits at each base. It says nothing
about who holds a place: Awareness paints that over this map during the game.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from ares.consts import BuildingSize
from sc2.position import Point2

from .topology import MapTopology, build_topology

# python-sc2's own gap: an expansion this close to a start is that start.
EXPANSION_GAP = 15.0
# A townhall this close to an expansion location stands on it.
BASE_SNAP_DISTANCE = 6.0


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
    # Centres where a 3x3 structure and its add-on fit in our main, as Ares'
    # placement solved them at the start (the ramp wall's left out); a site
    # may be taken by now.
    production_sites: tuple[Point2, ...] = ()
    # Per expansion, the 2x2 centres Ares solved around it at the start (the
    # ramp wall's left out), both as Ares' own keys; a spot may be taken by now.
    tower_sites: tuple[tuple[Point2, tuple[Point2, ...]], ...] = ()
    # Per expansion, the same for a 3x3 structure and its add-on.
    base_production_sites: tuple[tuple[Point2, tuple[Point2, ...]], ...] = ()
    # The expansions as each side would take them, natural first: Ares' ground
    # path distance from that start. Empty falls back to straight distance.
    own_expansion_order: tuple[Point2, ...] = ()
    enemy_expansion_order: tuple[Point2, ...] = ()

    @property
    def own_natural(self) -> Point2 | None:
        return _nth_expansion(self, self.own_expansion_order, self.own_start, 0)

    @property
    def enemy_natural(self) -> Point2 | None:
        return _nth_expansion(self, self.enemy_expansion_order, self.enemy_start, 0)

    @property
    def enemy_third(self) -> Point2 | None:
        return _nth_expansion(self, self.enemy_expansion_order, self.enemy_start, 1)


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
    own_start = as_point(bot.start_location)
    enemy_start = as_point(bot.enemy_start_locations[0])
    try:
        main_ramp = as_point(bot.main_base_ramp.top_center)
    except (AttributeError, IndexError, ValueError):
        main_ramp = own_start
    expansions = tuple(
        sorted(
            {as_point(location) for location in bot.expansion_locations_list},
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
        production_sites=_production_sites(bot),
        tower_sites=_tower_sites(bot),
        base_production_sites=_base_production_sites(bot),
        own_expansion_order=_expansion_order(bot, "get_own_expansions"),
        enemy_expansion_order=_expansion_order(bot, "get_enemy_expansions"),
    )


def _expansion_order(bot, request: str) -> tuple[Point2, ...]:
    """The expansions Ares ordered by ground path distance from that start."""

    try:
        ordered = getattr(bot.mediator, request)
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return ()
    return tuple(as_point(location) for location, _ in ordered or ())


def _nth_expansion(
    map_view: MapView, order: tuple[Point2, ...], start: Point2, index: int
) -> Point2 | None:
    """The nth expansion out from a start, the natural first. Without Ares'
    path order, straight distance answers it."""

    if order:
        return order[index] if index < len(order) else None
    starts = (map_view.own_start, map_view.enemy_start)
    away = sorted(
        (
            point
            for point in map_view.expansions
            if all(point.distance_to(base) > EXPANSION_GAP for base in starts)
        ),
        key=lambda point: (point.distance_to(start), point.x, point.y),
    )
    return away[index] if index < len(away) else None


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


def as_point(value) -> Point2:
    return Point2((float(value[0]), float(value[1])))


def _production_sites(bot) -> tuple[Point2, ...]:
    """Kept as Ares' own keys: its bookkeeping and its landing test compare
    positions exactly."""

    placements = _placements(bot)
    main = placements.get(bot.start_location, {}).get(BuildingSize.THREE_BY_THREE, {})
    return _off_the_wall(main)


def _tower_sites(bot) -> tuple[tuple[Point2, tuple[Point2, ...]], ...]:
    return tuple(
        sorted(
            (
                (base, _off_the_wall(sizes.get(BuildingSize.TWO_BY_TWO, {})))
                for base, sizes in _placements(bot).items()
            ),
            key=lambda item: (item[0].x, item[0].y),
        )
    )


def _base_production_sites(bot) -> tuple[tuple[Point2, tuple[Point2, ...]], ...]:
    return tuple(
        sorted(
            (
                (base, _off_the_wall(sizes.get(BuildingSize.THREE_BY_THREE, {})))
                for base, sizes in _placements(bot).items()
            ),
            key=lambda item: (item[0].x, item[0].y),
        )
    )


def _placements(bot) -> dict:
    try:
        return bot.mediator.get_placements_dict
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return {}


def _off_the_wall(sites: dict) -> tuple[Point2, ...]:
    return tuple(
        sorted(
            (site for site, info in sites.items() if not info.get("is_wall", False)),
            key=lambda point: (point.x, point.y),
        )
    )


def _map_data(bot):
    try:
        return bot.mediator.get_map_data_object
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return None

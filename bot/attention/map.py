"""The static map: read once per game, in ``on_start``, and frozen.

`read_map` reads what the physical map is -- playable area, starts, main ramp,
expansions, a pathable lattice and its `MapTopology` (regions, passages,
adjacency). It says nothing about who holds a place: Awareness paints that
over this map during the game.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sc2.position import Point2

from .topology import MapTopology, build_topology


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


def as_point(value) -> Point2:
    return Point2((float(value[0]), float(value[1])))


def _map_data(bot):
    try:
        return bot.mediator.get_map_data_object
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return None

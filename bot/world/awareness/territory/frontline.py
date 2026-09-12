"""A coarse frontline: where dominance changes sign between neighbouring samples."""

from __future__ import annotations

import math
from collections.abc import Sequence

from sc2.position import Point2

from ..spatial.kernel import distance_squared
from .model import TerritoryControl, TerritorySample

# Axis neighbours on the sampling lattice are one spacing apart and diagonal
# ones about 1.41; a pair within this many spacings is an axis neighbour.
_AXIS_REACH = 1.2


def lattice_edges(
    points: Sequence[Point2], spacing: float
) -> tuple[tuple[int, int], ...]:
    """Index pairs of samples one lattice step apart along an axis.

    Static: computed once per topology version. Points are bucketed into
    cells as wide as the reach, so each is compared only with its own and
    the eight surrounding cells.
    """

    if spacing <= 0.0:
        raise ValueError("spacing must be positive")
    size = spacing * _AXIS_REACH
    cells: dict[tuple[int, int], list[int]] = {}
    for index, point in enumerate(points):
        cells.setdefault(_cell(point, size), []).append(index)
    limit = size * size
    edges: list[tuple[int, int]] = []
    for index, point in enumerate(points):
        cell_x, cell_y = _cell(point, size)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in cells.get((cell_x + dx, cell_y + dy), ()):
                    if (
                        other > index
                        and distance_squared(point, points[other]) <= limit
                    ):
                        edges.append((index, other))
    return tuple(sorted(edges))


def frontline(
    samples: Sequence[TerritorySample], edges: Sequence[tuple[int, int]]
) -> tuple[Point2, ...]:
    """Points where friendly-leaning samples meet enemy-leaning ones.

    Only samples somebody holds take part -- the edge of our territory
    against empty map is a border, not a front. Each crossing is interpolated
    linearly along its edge, so the line slides continuously as dominance
    changes instead of jumping from sample to sample.
    """

    points: list[Point2] = []
    for first, second in edges:
        a, b = samples[first], samples[second]
        if TerritoryControl.UNCONTROLLED in (a.control, b.control):
            continue
        if a.reading.dominance > 0.0 >= b.reading.dominance:
            high, low = a, b
        elif b.reading.dominance > 0.0 >= a.reading.dominance:
            high, low = b, a
        else:
            continue
        upper, lower = high.reading.dominance, low.reading.dominance
        fraction = upper / (upper - lower)
        points.append(
            Point2(
                (
                    high.position.x + (low.position.x - high.position.x) * fraction,
                    high.position.y + (low.position.y - high.position.y) * fraction,
                )
            )
        )
    return tuple(dict.fromkeys(points))


def _cell(position: Point2, size: float) -> tuple[int, int]:
    return math.floor(position.x / size), math.floor(position.y / size)

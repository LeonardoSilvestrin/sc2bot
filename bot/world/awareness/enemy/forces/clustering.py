"""Spatial grouping of remembered enemy combat units, and what a group adds up to."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from typing import Any, TypeVar

from sc2.position import Point2

from ..heuristics import (
    EnemyForceHeuristics,
    combat_value,
    freshness,
    position_uncertainty,
)
from ..knowledge import EnemySighting
from .cluster import EnemyForceCluster

_Item = TypeVar("_Item")


def _last_position(sighting: EnemySighting) -> Point2:
    return sighting.last_position


def group_by_proximity(
    sightings: Sequence[_Item],
    link_radius: float,
    *,
    position_of: Callable[[Any], Point2] = _last_position,
) -> tuple[tuple[_Item, ...], ...]:
    """Connected components of "within ``link_radius`` of each other".

    Single linkage, so a strung-out column still reads as one group. Units
    are first bucketed into ``link_radius``-sized cells, so each one is only
    compared with the units in its own and the eight surrounding cells.
    Groups, and the units within each, keep the input order. Sightings are
    grouped by where they were last seen; ``position_of`` lets our own units
    be grouped the same way.
    """

    positions = tuple(position_of(sighting) for sighting in sightings)
    cells: dict[tuple[int, int], list[int]] = {}
    for index, item_position in enumerate(positions):
        cells.setdefault(_cell(item_position, link_radius), []).append(index)
    limit = link_radius * link_radius

    def neighbours(index: int) -> Iterator[int]:
        position = positions[index]
        cell_x, cell_y = _cell(position, link_radius)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in cells.get((cell_x + dx, cell_y + dy), ()):
                    other_position = positions[other]
                    if (other_position.x - position.x) ** 2 + (
                        other_position.y - position.y
                    ) ** 2 <= limit:
                        yield other

    grouped: set[int] = set()
    groups: list[tuple[_Item, ...]] = []
    for start in range(len(sightings)):
        if start in grouped:
            continue
        grouped.add(start)
        members = [start]
        frontier = [start]
        while frontier:
            for other in neighbours(frontier.pop()):
                if other not in grouped:
                    grouped.add(other)
                    members.append(other)
                    frontier.append(other)
        groups.append(tuple(sightings[index] for index in sorted(members)))
    return tuple(groups)


def _cell(position: Point2, size: float) -> tuple[int, int]:
    return math.floor(position.x / size), math.floor(position.y / size)


def centroid(members: Sequence[EnemySighting]) -> Point2:
    return Point2(
        (
            sum(member.last_position.x for member in members) / len(members),
            sum(member.last_position.y for member in members) / len(members),
        )
    )


def summarize(
    members: Sequence[EnemySighting],
    *,
    cluster_id: int,
    now: float,
    config: EnemyForceHeuristics,
) -> EnemyForceCluster:
    """Add one group up into a cluster reading.

    Confidence and position uncertainty are strength-weighted, so one fresh
    scout at the edge of an army seen twenty seconds ago does not make the
    whole army read as freshly seen.
    """

    center = centroid(members)
    strength = anti_air = anti_ground = 0.0
    weighted_freshness = weighted_age = 0.0
    for member in members:
        value = combat_value(member, config.combat)
        age = (
            max(0.0, now - member.last_seen_at)
            if member.last_seen_known
            else config.stale_after
        )
        strength += value.total
        anti_air += value.anti_air
        anti_ground += value.anti_ground
        weighted_freshness += value.total * freshness(age, config.stale_after)
        weighted_age += value.total * age

    return EnemyForceCluster(
        cluster_id=cluster_id,
        center=center,
        radius=max(center.distance_to(member.last_position) for member in members),
        position_uncertainty=position_uncertainty(
            weighted_age / strength if strength > 0.0 else 0.0, config
        ),
        combat_strength=strength,
        anti_air_strength=anti_air,
        anti_ground_strength=anti_ground,
        unit_count=len(members),
        visible_unit_count=sum(member.visible_now for member in members),
        unit_tags=tuple(member.tag for member in members),
        last_observed_at=max(
            (member.last_seen_at for member in members if member.last_seen_known),
            default=None,
        ),
        confidence=weighted_freshness / strength if strength > 0.0 else 0.0,
    )

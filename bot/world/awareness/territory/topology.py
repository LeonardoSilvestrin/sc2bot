"""The static half of territory, and the ground-access walk over it."""

from __future__ import annotations

import heapq
from collections.abc import Sequence
from dataclasses import dataclass

from sc2.position import Point2

from bot.world.attention import MapFacts, MapPassage, MapRegion

from .frontline import lattice_edges
from .model import locate_region


@dataclass(frozen=True, slots=True)
class TerritoryTopology:
    """Everything territory needs that only changes with the map.

    Built once per topology version: which spatial samples form each
    region, which regions each passage joins, where enemy ground forces come
    from, and which samples neighbour each other. The access graph has the
    regions as nodes ``0..R-1`` followed by the passages -- tens of nodes.
    """

    points: tuple[Point2, ...]
    regions: tuple[MapRegion, ...]
    passages: tuple[MapPassage, ...]
    # For each region, the indices of its samples in ``points``.
    region_samples: tuple[tuple[int, ...], ...]
    # For each sample, the key of its region (``None``: none).
    sample_regions: tuple[str | None, ...]
    adjacency: tuple[tuple[int, ...], ...]
    # Region nodes that always send enemy ground forces: the enemy starts.
    origins: frozenset[int]
    # Lattice axis neighbours, for the frontline.
    edges: tuple[tuple[int, int], ...]
    slots: tuple[tuple[Point2, str], ...]

    def locate(self, position: Point2) -> str | None:
        return locate_region(
            position,
            slots=self.slots,
            samples=zip(self.points, self.sample_regions, strict=True),
        )


def build_topology(
    points: tuple[Point2, ...], spacing: float, map_facts: MapFacts
) -> TerritoryTopology:
    index_of = {point: index for index, point in enumerate(points)}
    regions = map_facts.regions
    region_index = {region.key: index for index, region in enumerate(regions)}

    sample_regions: list[str | None] = [None] * len(points)
    region_samples: list[tuple[int, ...]] = []
    for region in regions:
        members = tuple(
            index
            for point in region.points
            if (index := index_of.get(point)) is not None
        )
        for index in members:
            sample_regions[index] = region.key
        region_samples.append(members)

    passages = tuple(
        passage
        for passage in map_facts.passages
        if passage.regions[0] != passage.regions[1]
        and all(key in region_index for key in passage.regions)
    )
    adjacency: list[list[int]] = [[] for _ in range(len(regions) + len(passages))]
    for offset, passage in enumerate(passages):
        node = len(regions) + offset
        for key in passage.regions:
            adjacency[node].append(region_index[key])
            adjacency[region_index[key]].append(node)

    slots = tuple(
        (expansion, region.key) for region in regions for expansion in region.expansions
    )
    origins = frozenset(
        region_index[origin]
        for start in map_facts.enemy_starts
        if (
            origin := locate_region(
                start, slots=slots, samples=zip(points, sample_regions, strict=True)
            )
        )
        is not None
    )
    return TerritoryTopology(
        points=points,
        regions=regions,
        passages=passages,
        region_samples=tuple(region_samples),
        sample_regions=tuple(sample_regions),
        adjacency=tuple(tuple(neighbours) for neighbours in adjacency),
        origins=origins,
        edges=lattice_edges(points, spacing),
        slots=slots,
    )


def ground_access(
    adjacency: Sequence[Sequence[int]],
    sources: Sequence[float],
    passes: Sequence[float],
) -> tuple[float, ...]:
    """How freely an enemy ground force reaches each node, 0..1.

    ``sources[n]`` is enemy force already standing at node ``n`` and
    ``passes[n]`` how freely one crosses it (1 - our hold). What leaves a
    node is ``max(source, arrived * pass)``, and a node's access is the best
    of what stands there and what arrives -- so its own hold never shields
    it, only the regions and passages in front of it do. It is the widest
    path under products of factors no greater than 1, so it settles in
    Dijkstra order: ``O((V + E) log V)`` on tens of nodes.
    """

    count = len(adjacency)
    arrived = [0.0] * count
    leaving = [max(0.0, float(value)) for value in sources]
    heap = [(-value, node) for node, value in enumerate(leaving) if value > 0.0]
    heapq.heapify(heap)
    while heap:
        negative, node = heapq.heappop(heap)
        if -negative < leaving[node]:
            continue
        for neighbour in adjacency[node]:
            if leaving[node] <= arrived[neighbour]:
                continue
            arrived[neighbour] = leaving[node]
            carried = max(sources[neighbour], arrived[neighbour] * passes[neighbour])
            if carried > leaving[neighbour]:
                leaving[neighbour] = carried
                heapq.heappush(heap, (-carried, neighbour))
    return tuple(
        min(1.0, max(source, arrival))
        for source, arrival in zip(sources, arrived, strict=True)
    )

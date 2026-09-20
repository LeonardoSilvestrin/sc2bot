"""Immutable, static knowledge of the map's ground topology.

The Ares MapAnalyzer owns the expensive geometric decomposition.  This module
copies only its regions and passages into small deterministic values aligned
with our pathable lattice.  Nothing here describes who controls a place or
what the bot should do there.

Identity is static; accessibility is not.  The lattice is read off
``game_info.pathing_grid``, which the game hands us with mineral walls and
destructible rocks already counted as walkable ground, so every passage a map
can ever have exists in the topology from the first frame -- with the same id,
between the same regions, for the whole game.  What a blocker changes is only
`MapPassage.state`: a passage whose blockers are all gone is ``OPEN``, one that
still has any is ``CLOSED``.  `bot.attention.passages` follows the blocker tags
frame by frame and hands back a topology with the new states; routines that ask
about connectivity ask for open passages.
"""

from __future__ import annotations

import heapq
import math
from collections import Counter, deque
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import combinations
from typing import Literal

import numpy as np
from sc2.position import Point2

PassageKind = Literal["choke", "border"]
PassageState = Literal["open", "closed", "unknown"]
OPEN: PassageState = "open"
CLOSED: PassageState = "closed"
# We hold blockers for this passage but could not read the world this frame.
UNKNOWN: PassageState = "unknown"
# What stands in a passage.  ``mixed`` is a passage several kinds block at once.
BlockerType = Literal["mineral_wall", "destructible", "mixed"]
MINERAL_WALL: BlockerType = "mineral_wall"
DESTRUCTIBLE: BlockerType = "destructible"
MIXED: BlockerType = "mixed"
# How far around a passage its blockers are looked for and judged.  Wide enough
# to hold both sides of any choke, tight enough that the way round is outside.
BLOCKER_WINDOW = 16.0
ChokeReason = Literal[
    "between_regions",
    "splits_region",
    "no_position",
    "no_region",
    "no_lattice_crossing",
    "does_not_separate",
    "side_too_small",
]
ACCEPTED_CHOKE_REASONS: frozenset[str] = frozenset({"between_regions", "splits_region"})
# MapAnalyzer's MIN_REGION_AREA: less ground than this is no area at all.
_MIN_REGION_AREA = 25.0


@dataclass(frozen=True, slots=True)
class MapRegion:
    region_id: str
    center: Point2
    sample_indices: tuple[int, ...] = ()
    # More than one expansion may honestly share one open physical region.
    expansions: tuple[Point2, ...] = ()


@dataclass(frozen=True, slots=True)
class MapBlocker:
    """One neutral object that stands in the way: a mineral wall's patch or a
    destructible rock, as the game shows it, with the cells it covers."""

    tag: int
    blocker_type: BlockerType
    position: Point2
    cells: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class MapPassage:
    """A ground connection shared by two or more regions.

    ``border`` passages are clear lattice borders for which MapAnalyzer did
    not report a geometric choke.  Their width is deliberately unknown.

    Everything but `state` is the passage's identity and never changes: the
    same id joins the same regions at the same place from the first frame to
    the last.  `blocker_tags` are the neutral objects whose presence closes it,
    all of them, so losing some of a mineral wall leaves the passage closed.
    """

    passage_id: str
    position: Point2
    width: float | None
    regions: tuple[str, ...]
    kind: PassageKind
    # What stands in it, when something does.
    blocker_type: BlockerType | None = None
    blocker_tags: tuple[int, ...] = ()
    state: PassageState = OPEN

    @property
    def is_open(self) -> bool:
        return self.state == OPEN

    @property
    def is_closed(self) -> bool:
        """Closed, or unknown: nothing walks through a passage we cannot
        vouch for."""

        return self.state != OPEN

    @property
    def has_blockers(self) -> bool:
        return bool(self.blocker_tags)


# The name the rest of the bot may read it by; `MapPassage` is its history.
Passage = MapPassage


@dataclass(frozen=True, slots=True)
class ChokeCandidate:
    """One MapAnalyzer choke and what the topology made of it; debug only.

    ``source_regions`` are the regions MapAnalyzer gave the choke, which for
    its terrain chokes is often one region twice.
    """

    position: Point2 | None
    source_regions: tuple[str, ...]
    reason: ChokeReason
    passage_id: str | None = None

    @property
    def accepted(self) -> bool:
        return self.reason in ACCEPTED_CHOKE_REASONS


@dataclass(frozen=True, slots=True)
class RegionSplit:
    """A MapAnalyzer region cut into sub-regions by chokes lying inside it."""

    region_id: str
    into: tuple[str, ...]
    passage_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MapTopology:
    regions: tuple[MapRegion, ...] = ()
    passages: tuple[MapPassage, ...] = ()
    # region_id -> ((neighbour_region_id, passage_id), ...)
    adjacency: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    expansion_to_region: tuple[tuple[Point2, str], ...] = ()
    own_start_region: str | None = None
    enemy_start_region: str | None = None
    choke_candidates: tuple[ChokeCandidate, ...] = ()
    region_splits: tuple[RegionSplit, ...] = ()

    def region(self, region_id: str) -> MapRegion | None:
        return next(
            (region for region in self.regions if region.region_id == region_id), None
        )

    def passage(self, passage_id: str) -> MapPassage | None:
        return next(
            (
                passage
                for passage in self.passages
                if passage.passage_id == passage_id
            ),
            None,
        )

    def neighbours(
        self, region_id: str, *, open_only: bool = False
    ) -> tuple[tuple[str, str], ...]:
        """``(neighbour, passage_id)`` of every passage out of ``region_id``;
        with ``open_only`` only the ones something can walk through now."""

        links = next((links for key, links in self.adjacency if key == region_id), ())
        if not open_only:
            return links
        closed = self._closed_ids()
        return tuple(link for link in links if link[1] not in closed)

    def expansion_region(self, expansion: Point2) -> str | None:
        return next(
            (
                region
                for position, region in self.expansion_to_region
                if position == expansion
            ),
            None,
        )

    # --- accessibility, which the game changes under a static identity ---

    def open_passages(self) -> tuple[MapPassage, ...]:
        """The passages something can walk through right now."""

        return tuple(passage for passage in self.passages if passage.is_open)

    def closed_passages(self) -> tuple[MapPassage, ...]:
        return tuple(passage for passage in self.passages if passage.is_closed)

    def blocked_passages(self) -> tuple[MapPassage, ...]:
        """Every passage a blocker was ever found in, open by now or not."""

        return tuple(passage for passage in self.passages if passage.has_blockers)

    def open_adjacency(self) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
        """`adjacency` without the passages that are shut; the same shape, so
        anything that walks the region graph can take it instead."""

        closed = self._closed_ids()
        if not closed:
            return self.adjacency
        return tuple(
            (
                region_id,
                tuple(link for link in links if link[1] not in closed),
            )
            for region_id, links in self.adjacency
        )

    def connected_regions(
        self, region_id: str, *, open_only: bool = True
    ) -> frozenset[str]:
        """Every region reachable on foot from ``region_id``, itself included.

        By open passages only: this answers where the army can walk now, not
        what the map would look like with every rock down.
        """

        links = dict(self.open_adjacency() if open_only else self.adjacency)
        if region_id not in links:
            return frozenset()
        found = {region_id}
        frontier = deque([region_id])
        while frontier:
            for neighbour, _ in links.get(frontier.popleft(), ()):
                if neighbour not in found:
                    found.add(neighbour)
                    frontier.append(neighbour)
        return frozenset(found)

    def route(
        self, start: str | None, goal: str | None, *, open_only: bool = True
    ) -> tuple[str, ...]:
        """The regions walked from ``start`` to ``goal``, both included; empty
        when there is no way. Fewest passages, ties by region id."""

        links = dict(self.open_adjacency() if open_only else self.adjacency)
        if start is None or goal is None or start not in links or goal not in links:
            return ()
        if start == goal:
            return (start,)
        came_from: dict[str, str] = {start: start}
        frontier = deque([start])
        while frontier:
            region_id = frontier.popleft()
            for neighbour, _ in sorted(links.get(region_id, ())):
                if neighbour in came_from:
                    continue
                came_from[neighbour] = region_id
                if neighbour == goal:
                    walked = [goal]
                    while walked[-1] != start:
                        walked.append(came_from[walked[-1]])
                    return tuple(reversed(walked))
                frontier.append(neighbour)
        return ()

    def reachable(
        self, start: str | None, goal: str | None, *, open_only: bool = True
    ) -> bool:
        return bool(self.route(start, goal, open_only=open_only))

    def with_passage_states(
        self, states: Mapping[str, PassageState]
    ) -> MapTopology:
        """The same topology with these passage states; ``self`` when nothing
        moved, so a caller can tell a changed frame by identity."""

        if all(
            passage.state == states.get(passage.passage_id, passage.state)
            for passage in self.passages
        ):
            return self
        return replace(
            self,
            passages=tuple(
                replace(passage, state=states[passage.passage_id])
                if passage.passage_id in states
                else passage
                for passage in self.passages
            ),
        )

    def _closed_ids(self) -> frozenset[str]:
        return frozenset(
            passage.passage_id for passage in self.passages if passage.is_closed
        )


@dataclass(slots=True)
class _Choke:
    """Build-time working record of one MapAnalyzer choke."""

    position: Point2 | None
    width: float | None
    area: float
    cells: frozenset[tuple[int, int]]
    source_regions: tuple[str, ...]
    reason: ChokeReason | None = None
    regions: tuple[str, ...] = ()
    passage_id: str | None = None


def build_topology(
    pathing_grid: np.ndarray,
    lattice: tuple[Point2, ...],
    lattice_spacing: float,
    expansions: Sequence[Point2],
    own_start: Point2,
    enemy_start: Point2,
    *,
    map_data=None,
    blockers: Sequence[MapBlocker] = (),
) -> MapTopology:
    """Build one canonical topology from immutable map geometry.

    ``blockers`` are the neutral objects standing on the map at the start.
    They never change what a passage is, only whether it is open: a passage
    they seal is born ``CLOSED`` and stays that way until they are all gone.
    """

    grid = np.asarray(pathing_grid)
    canonical_expansions = tuple(sorted(set(expansions), key=_point_key))
    sample_edges = _sample_edges(grid, lattice, lattice_spacing)
    sample_neighbours = _neighbours(len(lattice), sample_edges)

    raw_regions = sorted(_raw_regions(map_data), key=_raw_region_key)
    raw_ids = {
        id(region): f"region:{index}" for index, region in enumerate(raw_regions)
    }
    labels_to_ids = {
        _label(region): raw_ids[id(region)]
        for region in raw_regions
        if _label(region) is not None
    }

    def raw_region_id(value) -> str | None:
        if value is None:
            return None
        return raw_ids.get(id(value)) or labels_to_ids.get(_label(value))

    in_region = _safe_attr(map_data, "in_region_p")
    initial_labels = [
        raw_region_id(
            _call_region(in_region, (math.floor(point.x), math.floor(point.y)))
        )
        for point in lattice
    ]
    sample_regions = _flood_regions(initial_labels, sample_neighbours)

    region_geometry: dict[str, tuple[Point2, tuple[int, ...]]] = {}
    for raw in raw_regions:
        region_id = raw_ids[id(raw)]
        members = tuple(
            index for index, owner in enumerate(sample_regions) if owner == region_id
        )
        center = _point(_safe_attr(raw, "center")) or _mean(
            tuple(lattice[index] for index in members)
        )
        if center is not None:
            region_geometry[region_id] = (center, members)

    # A pathable component with no MapAnalyzer region is still real map space.
    # Do not make transit regions inside seeded components: ramps and choke
    # strips are intentionally absent from MapAnalyzer's region polygons.
    for component in _unowned_components(sample_regions, sample_neighbours):
        region_id = f"transit:{len(region_geometry)}"
        members = tuple(sorted(component))
        center = _mean(tuple(lattice[index] for index in members))
        if center is None:
            continue
        region_geometry[region_id] = (center, members)
        for index in members:
            sample_regions[index] = region_id

    # MapAnalyzer's terrain chokes usually name one region on both sides: the
    # region polygon runs straight through them.  Such a choke is judged by
    # whether it really cuts that region's ground in two.
    chokes = _read_chokes(map_data, raw_region_id)
    internal: dict[str, list[_Choke]] = {}
    for choke in chokes:
        known = tuple(key for key in choke.source_regions if key in region_geometry)
        if choke.position is None:
            choke.reason = "no_position"
        elif not known:
            choke.reason = "no_region"
        elif len(known) == 1:
            internal.setdefault(known[0], []).append(choke)
    splits: dict[str, tuple[str, ...]] = {}
    for host, hosted in sorted(internal.items()):
        children = _split_region(
            host,
            hosted,
            lattice,
            sample_edges,
            sample_regions,
            region_geometry,
            lattice_spacing,
        )
        if children:
            splits[host] = children

    valid_regions = set(region_geometry)

    def resolve(region_id: str | None, point: Point2) -> str | None:
        """A MapAnalyzer region id as the (sub-)region that holds ``point``."""

        children = splits.get(region_id) if region_id is not None else None
        if children:
            return _reachable_region(
                point, grid, lattice, sample_regions, allowed=frozenset(children)
            )
        return region_id if region_id in valid_regions else None

    def direct_region(point: Point2) -> str | None:
        return resolve(raw_region_id(_call_region(in_region, point)), point)

    for choke in chokes:
        if choke.reason is not None or choke.position is None:
            continue
        position = choke.position
        choke.regions = tuple(
            sorted(
                {
                    region_id
                    for source in choke.source_regions
                    if (region_id := resolve(source, position)) is not None
                }
            )
        )
        choke.reason = "between_regions" if len(choke.regions) >= 2 else "no_region"

    expansion_mapping: list[tuple[Point2, str]] = []
    expansion_members: dict[str, list[Point2]] = {key: [] for key in valid_regions}
    for index, expansion in enumerate(canonical_expansions):
        region_id = direct_region(expansion) or _reachable_region(
            expansion, grid, lattice, sample_regions
        )
        if region_id not in valid_regions:
            region_id = _nearest_region(expansion, region_geometry)
        if region_id is None:
            region_id = f"expansion:{index}"
            region_geometry[region_id] = (expansion, ())
            expansion_members[region_id] = []
            valid_regions.add(region_id)
        expansion_mapping.append((expansion, region_id))
        expansion_members.setdefault(region_id, []).append(expansion)

    passages = _blocked(
        _passages(chokes, lattice, sample_regions, sample_edges, lattice_spacing),
        blockers,
        grid,
        lattice,
        sample_regions,
    )
    regions = tuple(
        MapRegion(
            region_id=region_id,
            center=center,
            sample_indices=members,
            expansions=tuple(expansion_members.get(region_id, ())),
        )
        for region_id, (center, members) in sorted(region_geometry.items())
    )
    adjacency = _adjacency(regions, passages)

    def locate(point: Point2) -> str | None:
        region_id = direct_region(point)
        if region_id is not None:
            return region_id
        nearby_expansion = min(
            expansion_mapping,
            key=lambda item: (point.distance_to(item[0]), item[1]),
            default=None,
        )
        if nearby_expansion is not None and point.distance_to(
            nearby_expansion[0]
        ) <= max(3.0, lattice_spacing):
            return nearby_expansion[1]
        return _reachable_region(
            point, grid, lattice, sample_regions
        ) or _nearest_region(point, region_geometry)

    topology = MapTopology(
        regions=regions,
        passages=passages,
        adjacency=adjacency,
        expansion_to_region=tuple(expansion_mapping),
        own_start_region=locate(own_start),
        enemy_start_region=locate(enemy_start),
        choke_candidates=tuple(
            ChokeCandidate(
                position=choke.position,
                source_regions=choke.source_regions,
                reason=choke.reason or "no_region",
                passage_id=choke.passage_id,
            )
            for choke in chokes
        ),
        region_splits=tuple(
            RegionSplit(
                region_id=host,
                into=children,
                passage_ids=tuple(
                    sorted(
                        {
                            choke.passage_id
                            for choke in internal[host]
                            if choke.passage_id is not None
                        }
                    )
                ),
            )
            for host, children in sorted(splits.items())
        ),
    )
    _validate(topology, canonical_expansions)
    return topology


def _raw_regions(map_data) -> tuple:
    raw = _safe_attr(map_data, "regions", ())
    if isinstance(raw, Mapping):
        raw = raw.values()
    try:
        return tuple(raw or ())
    except (RuntimeError, TypeError):
        return ()


def _raw_region_key(region) -> tuple:
    label = _label(region)
    center = _point(_safe_attr(region, "center"))
    try:
        numeric_label = (0, float(label), "")
    except (TypeError, ValueError):
        numeric_label = (1, 0.0, "" if label is None else str(label))
    return (*numeric_label, *_point_key(center or Point2((math.inf, math.inf))))


def _label(region):
    value = _safe_attr(region, "label")
    try:
        hash(value)
    except TypeError:
        return str(value)
    return value


def _read_chokes(map_data, raw_region_id) -> list[_Choke]:
    chokes: list[_Choke] = []
    for choke in _items(map_data, "map_chokes"):
        points = tuple(
            filter(None, (_point(point) for point in _items(choke, "points")))
        )
        cells = frozenset((math.floor(point.x), math.floor(point.y)) for point in points)
        chokes.append(
            _Choke(
                position=_point(_safe_attr(choke, "center")) or _mean(points),
                width=_choke_width(choke),
                area=_choke_area(choke, cells),
                cells=cells,
                source_regions=tuple(
                    sorted(
                        {
                            region_id
                            for raw in _items(choke, "regions")
                            if (region_id := raw_region_id(raw)) is not None
                        }
                    )
                ),
            )
        )
    chokes.sort(
        key=lambda choke: (
            _point_key(choke.position or Point2((math.inf, math.inf))),
            choke.source_regions,
            len(choke.cells),
            min(choke.cells, default=(0, 0)),
        )
    )
    return chokes


def _split_region(
    host: str,
    chokes: Sequence[_Choke],
    lattice: tuple[Point2, ...],
    sample_edges: Sequence[tuple[int, int]],
    owners: list[str | None],
    geometry: dict[str, tuple[Point2, tuple[int, ...]]],
    spacing: float,
) -> tuple[str, ...]:
    """Cut ``host`` along the chokes MapAnalyzer placed wholly inside it.

    The lattice steps crossing any of these chokes are removed and what falls
    apart are pieces.  A piece with less ground than a choke it touches is a
    notch in the wall or the choke's own strip, so it rejoins its largest
    neighbour across that choke.  A choke is accepted when its steps still
    join two different pieces; only then is ``host`` replaced by one
    sub-region per such piece.  Pieces no accepted choke reaches (ground the
    coarse lattice never joined) go to the nearest sub-region.  Sets every
    choke's reason; mutates ``owners`` and ``geometry`` only on a split.
    """

    members = geometry[host][1]
    inside = set(members)
    local = [edge for edge in sample_edges if edge[0] in inside and edge[1] in inside]
    crossings = [
        tuple(
            edge
            for edge in local
            if any(
                cell in choke.cells
                for cell in _segment_cells(lattice[edge[0]], lattice[edge[1]])
            )
        )
        for choke in chokes
    ]
    blocked = {edge for edges in crossings for edge in edges}
    piece_of = _pieces(members, [edge for edge in local if edge not in blocked])
    initial_size = Counter(piece_of.values())
    size = dict(initial_size)
    root = {piece: piece for piece in size}

    def find(piece: int) -> int:
        while root[piece] != piece:
            root[piece] = root[root[piece]]
            piece = root[piece]
        return piece

    sample_area = spacing * spacing
    while True:
        need: dict[int, float] = {}
        links: dict[int, set[int]] = {}
        for choke, edges in zip(chokes, crossings, strict=True):
            for first, second in edges:
                pair = (find(piece_of[first]), find(piece_of[second]))
                for piece in pair:
                    need[piece] = max(need.get(piece, 0.0), choke.area)
                if pair[0] != pair[1]:
                    links.setdefault(pair[0], set()).add(pair[1])
                    links.setdefault(pair[1], set()).add(pair[0])
        small = [
            piece
            for piece, area in need.items()
            if size[piece] * sample_area < area and links.get(piece)
        ]
        if not small:
            break
        victim = min(small, key=lambda piece: (size[piece], piece))
        target = max(links[victim], key=lambda piece: (size[piece], -piece))
        root[victim] = target
        size[target] += size[victim]

    touched_by: list[tuple[int, ...]] = []
    for choke, edges in zip(chokes, crossings, strict=True):
        ends = {sample for edge in edges for sample in edge}
        touched = tuple(sorted({find(piece_of[sample]) for sample in ends}))
        touched_by.append(touched)
        if not edges:
            choke.reason = "no_lattice_crossing"
        elif len(touched) >= 2:
            choke.reason = "splits_region"
        elif (
            sum(
                initial_size[piece] * sample_area >= _MIN_REGION_AREA
                for piece in {piece_of[sample] for sample in ends}
            )
            >= 2
        ):
            choke.reason = "side_too_small"
        else:
            choke.reason = "does_not_separate"

    anchored = sorted(
        {
            piece
            for choke, touched in zip(chokes, touched_by, strict=True)
            if choke.reason == "splits_region"
            for piece in touched
        }
    )
    if not anchored:
        return ()
    by_piece: dict[int, list[int]] = {}
    for sample in members:
        by_piece.setdefault(find(piece_of[sample]), []).append(sample)
    groups = {piece: list(by_piece[piece]) for piece in anchored}
    for piece, samples in sorted(by_piece.items()):
        if piece in groups:
            continue
        nearest = min(
            anchored,
            key=lambda other: (
                min(
                    lattice[first].distance_to(lattice[second])
                    for first in samples
                    for second in by_piece[other]
                ),
                other,
            ),
        )
        groups[nearest].extend(samples)

    ordered = sorted(anchored, key=lambda piece: min(groups[piece]))
    child_of = {piece: f"{host}.{index}" for index, piece in enumerate(ordered)}
    del geometry[host]
    for piece in ordered:
        samples = tuple(sorted(groups[piece]))
        for sample in samples:
            owners[sample] = child_of[piece]
        geometry[child_of[piece]] = (
            _mean(tuple(lattice[sample] for sample in samples)) or lattice[samples[0]],
            samples,
        )
    for choke, touched in zip(chokes, touched_by, strict=True):
        if choke.reason == "splits_region":
            choke.regions = tuple(sorted(child_of[piece] for piece in touched))
    return tuple(child_of[piece] for piece in ordered)


def _pieces(
    members: Sequence[int], edges: Sequence[tuple[int, int]]
) -> dict[int, int]:
    """Connected components of ``members``, each named by its lowest sample."""

    neighbours: dict[int, list[int]] = {sample: [] for sample in members}
    for first, second in edges:
        neighbours[first].append(second)
        neighbours[second].append(first)
    piece_of: dict[int, int] = {}
    for start in sorted(members):
        if start in piece_of:
            continue
        piece_of[start] = start
        queue = deque([start])
        while queue:
            sample = queue.popleft()
            for other in neighbours[sample]:
                if other not in piece_of:
                    piece_of[other] = start
                    queue.append(other)
    return piece_of


def _sample_edges(
    grid: np.ndarray, lattice: tuple[Point2, ...], spacing: float
) -> tuple[tuple[int, int], ...]:
    if spacing <= 0.0:
        return ()
    index_of = {_point_key(point): index for index, point in enumerate(lattice)}
    edges: list[tuple[int, int]] = []
    for index, point in enumerate(lattice):
        for dx, dy in ((spacing, 0.0), (0.0, spacing)):
            other = index_of.get(_point_key(Point2((point.x + dx, point.y + dy))))
            if other is not None and _straight_step_clear(grid, point, lattice[other]):
                edges.append((index, other))
    return tuple(edges)


def _neighbours(
    count: int, edges: Sequence[tuple[int, int]]
) -> tuple[tuple[int, ...], ...]:
    result: list[list[int]] = [[] for _ in range(count)]
    for first, second in edges:
        result[first].append(second)
        result[second].append(first)
    return tuple(tuple(sorted(items)) for items in result)


def _flood_regions(
    initial: Sequence[str | None], neighbours: Sequence[Sequence[int]]
) -> list[str | None]:
    """Nearest seeded region per sample, tied by canonical region id."""

    owners = list(initial)
    fixed = tuple(initial)
    best: list[tuple[int, str] | None] = [None] * len(owners)
    heap: list[tuple[int, str, int]] = []
    for index, region_id in enumerate(initial):
        if region_id is None:
            continue
        best[index] = (0, region_id)
        heapq.heappush(heap, (0, region_id, index))
    while heap:
        distance, region_id, index = heapq.heappop(heap)
        if best[index] != (distance, region_id):
            continue
        owners[index] = region_id
        for other in neighbours[index]:
            if fixed[other] is not None and fixed[other] != region_id:
                continue
            candidate = (distance + 1, region_id)
            if best[other] is None or candidate < best[other]:
                best[other] = candidate
                heapq.heappush(heap, (*candidate, other))
    return owners


def _unowned_components(
    owners: Sequence[str | None], neighbours: Sequence[Sequence[int]]
) -> tuple[tuple[int, ...], ...]:
    unseen = {index for index, owner in enumerate(owners) if owner is None}
    components: list[tuple[int, ...]] = []
    while unseen:
        start = min(unseen)
        unseen.remove(start)
        queue = deque([start])
        component: list[int] = []
        while queue:
            index = queue.popleft()
            component.append(index)
            for other in neighbours[index]:
                if other in unseen:
                    unseen.remove(other)
                    queue.append(other)
        components.append(tuple(sorted(component)))
    return tuple(components)


def _passages(
    chokes: Sequence[_Choke],
    lattice: tuple[Point2, ...],
    sample_regions: Sequence[str | None],
    sample_edges: Sequence[tuple[int, int]],
    spacing: float,
) -> tuple[MapPassage, ...]:
    """Accepted chokes, then clear borders no choke already represents.

    Stamps each accepted choke with the id of the passage it became.
    """

    descriptors: list[
        tuple[PassageKind, Point2, float | None, tuple[str, ...], tuple[_Choke, ...]]
    ] = []
    for strip in _strips(
        [
            choke
            for choke in chokes
            if choke.reason in ACCEPTED_CHOKE_REASONS and choke.position is not None
        ]
    ):
        widths = [choke.width for choke in strip if choke.width is not None]
        descriptors.append(
            (
                "choke",
                _mean(tuple(choke.position for choke in strip if choke.position)),
                min(widths, default=None),
                strip[0].regions,
                strip,
            )
        )

    represented = {
        pair
        for _, _, _, regions, _ in descriptors
        for pair in combinations(regions, 2)
    }
    crossings: dict[tuple[str, str], list[Point2]] = {}
    for first, second in sample_edges:
        first_region, second_region = sample_regions[first], sample_regions[second]
        if (
            first_region is None
            or second_region is None
            or first_region == second_region
        ):
            continue
        pair = tuple(sorted((first_region, second_region)))
        if pair in represented:
            continue
        start, end = lattice[first], lattice[second]
        crossings.setdefault(pair, []).append(
            Point2(((start.x + end.x) / 2.0, (start.y + end.y) / 2.0))
        )
    for pair, midpoints in sorted(crossings.items()):
        for cluster in _clusters(midpoints, spacing):
            position = _mean(cluster)
            if position is not None:
                descriptors.append(("border", position, None, pair, ()))

    descriptors.sort(key=_passage_key)
    counters = {"choke": 0, "border": 0}
    result: list[MapPassage] = []
    for kind, position, width, regions, sources in descriptors:
        index = counters[kind]
        counters[kind] += 1
        passage_id = f"{kind}:{index}"
        for source in sources:
            source.passage_id = passage_id
        result.append(
            MapPassage(
                passage_id=passage_id,
                position=position,
                width=width,
                regions=regions,
                kind=kind,
            )
        )
    return tuple(result)


def _blocked(
    passages: Sequence[MapPassage],
    blockers: Sequence[MapBlocker],
    grid: np.ndarray,
    lattice: tuple[Point2, ...],
    sample_regions: Sequence[str | None],
) -> tuple[MapPassage, ...]:
    """The passages, each carrying the blockers that seal it, and its state.

    A blocker is put on a passage when it is what shuts it: with the blocker's
    group stamped into the ground, the two sides of that passage no longer
    reach each other *near the passage*.  Judging it in a window keeps the
    answer local -- the long way round the map is not an answer to "does this
    rock close this choke" -- and stamping a whole group at once is what a
    mineral wall needs, since taking one patch out of fifteen opens nothing.
    """

    groups = _blocker_groups(blockers)
    if not groups:
        return tuple(passages)
    cells_of = _region_cells(lattice, sample_regions)
    result: list[MapPassage] = []
    for passage in passages:
        found = _sealing_groups(passage, groups, grid, cells_of)
        if not found:
            result.append(passage)
            continue
        members = [blocker for group in found for blocker in group]
        kinds = {blocker.blocker_type for blocker in members}
        result.append(
            replace(
                passage,
                blocker_type=kinds.pop() if len(kinds) == 1 else MIXED,
                blocker_tags=tuple(sorted({blocker.tag for blocker in members})),
                state=CLOSED,
            )
        )
    return tuple(result)


def _blocker_groups(
    blockers: Sequence[MapBlocker],
) -> tuple[tuple[MapBlocker, ...], ...]:
    """Blockers whose cells touch, as one thing to remove.

    A mineral wall is fifteen patches; an expedition gate is two rocks side by
    side.  Only the whole group opens ground, so only the whole group is asked
    whether it closes any.
    """

    ordered = sorted(blockers, key=lambda b: (b.blocker_type, *_point_key(b.position)))
    parent = list(range(len(ordered)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owner: dict[tuple[int, int], int] = {}
    for index, blocker in enumerate(ordered):
        for x, y in blocker.cells:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    other = owner.get((x + dx, y + dy))
                    if other is not None:
                        parent[find(other)] = find(index)
        for cell in blocker.cells:
            owner[cell] = index
    groups: dict[int, list[MapBlocker]] = {}
    for index, blocker in enumerate(ordered):
        groups.setdefault(find(index), []).append(blocker)
    return tuple(tuple(group) for _, group in sorted(groups.items()))


def _region_cells(
    lattice: tuple[Point2, ...], sample_regions: Sequence[str | None]
) -> dict[str, tuple[tuple[int, int], ...]]:
    cells: dict[str, list[tuple[int, int]]] = {}
    for point, region_id in zip(lattice, sample_regions, strict=True):
        if region_id is not None:
            cells.setdefault(region_id, []).append(
                (math.floor(point.x), math.floor(point.y))
            )
    return {key: tuple(value) for key, value in cells.items()}


def _sealing_groups(
    passage: MapPassage,
    groups: Sequence[Sequence[MapBlocker]],
    grid: np.ndarray,
    region_cells: Mapping[str, tuple[tuple[int, int], ...]],
) -> tuple[tuple[MapBlocker, ...], ...]:
    """The groups whose presence cuts this passage inside its own window."""

    radius = max(BLOCKER_WINDOW, (passage.width or 0.0) * 1.5)
    near = [
        tuple(group)
        for group in groups
        if any(
            _within(cell, passage.position, radius)
            for blocker in group
            for cell in blocker.cells
        )
    ]
    if not near:
        return ()
    window = _window(grid, passage.position, radius)
    sides = [
        frozenset(
            cell
            for cell in region_cells.get(region_id, ())
            if cell in window
        )
        for region_id in passage.regions
    ]
    # Judged against the first region, which every other one is a side of.
    pairs = [
        (sides[0], other)
        for other in sides[1:]
        if sides[0] and other and _joined(window, frozenset(), sides[0], other)
    ]
    if not pairs:
        return ()
    return tuple(
        group
        for group in near
        if any(
            not _joined(
                window,
                frozenset(cell for blocker in group for cell in blocker.cells),
                first,
                second,
            )
            for first, second in pairs
        )
    )


def _window(
    grid: np.ndarray, centre: Point2, radius: float
) -> frozenset[tuple[int, int]]:
    """The pathable cells within ``radius`` of ``centre``."""

    low_x, low_y = math.floor(centre.x - radius), math.floor(centre.y - radius)
    high_x, high_y = math.ceil(centre.x + radius), math.ceil(centre.y + radius)
    return frozenset(
        (x, y)
        for x in range(low_x, high_x + 1)
        for y in range(low_y, high_y + 1)
        if _pathable(grid, x, y) and _within((x, y), centre, radius)
    )


def _within(cell: tuple[int, int], centre: Point2, radius: float) -> bool:
    return math.hypot(cell[0] + 0.5 - centre.x, cell[1] + 0.5 - centre.y) <= radius


def _joined(
    window: frozenset[tuple[int, int]],
    blocked: frozenset[tuple[int, int]],
    start: Collection[tuple[int, int]],
    goal: Collection[tuple[int, int]],
) -> bool:
    """Whether ``start`` reaches ``goal`` inside ``window`` with ``blocked``
    stamped out of the ground."""

    targets = frozenset(goal) - blocked
    queue = deque(cell for cell in start if cell in window and cell not in blocked)
    seen = set(queue)
    if not targets or not queue:
        return False
    while queue:
        x, y = queue.popleft()
        if (x, y) in targets:
            return True
        for dx, dy in ((-1, 0), (0, -1), (0, 1), (1, 0)):
            other = (x + dx, y + dy)
            if other in window and other not in blocked and other not in seen:
                seen.add(other)
                queue.append(other)
    return False


def _strips(chokes: Sequence[_Choke]) -> tuple[tuple[_Choke, ...], ...]:
    """Chokes joining the same regions through touching cells, grouped.

    MapAnalyzer often reports one constriction as parallel one-cell strips;
    they are one passage.  Chokes without cells are never grouped.
    """

    parent = list(range(len(chokes)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for first, second in combinations(range(len(chokes)), 2):
        if chokes[first].regions == chokes[second].regions and _cells_touch(
            chokes[first].cells, chokes[second].cells
        ):
            parent[find(second)] = find(first)
    groups: dict[int, list[_Choke]] = {}
    for index, choke in enumerate(chokes):
        groups.setdefault(find(index), []).append(choke)
    return tuple(tuple(group) for group in groups.values())


def _cells_touch(
    first: frozenset[tuple[int, int]], second: frozenset[tuple[int, int]]
) -> bool:
    if len(first) > len(second):
        first, second = second, first
    return any(
        (x + dx, y + dy) in second
        for x, y in first
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
    )


def _clusters(
    points: Sequence[Point2], spacing: float
) -> tuple[tuple[Point2, ...], ...]:
    remaining = set(range(len(points)))
    result: list[tuple[Point2, ...]] = []
    limit = max(1.0, spacing * 1.5)
    while remaining:
        start = min(remaining, key=lambda index: _point_key(points[index]))
        remaining.remove(start)
        queue = deque([start])
        members: list[Point2] = []
        while queue:
            index = queue.popleft()
            members.append(points[index])
            connected = sorted(
                (
                    other
                    for other in remaining
                    if points[index].distance_to(points[other]) <= limit
                ),
                key=lambda other: _point_key(points[other]),
            )
            for other in connected:
                remaining.remove(other)
                queue.append(other)
        result.append(tuple(sorted(members, key=_point_key)))
    return tuple(result)


def _adjacency(
    regions: Sequence[MapRegion], passages: Sequence[MapPassage]
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    links: dict[str, list[tuple[str, str]]] = {
        region.region_id: [] for region in regions
    }
    for passage in passages:
        for first, second in combinations(passage.regions, 2):
            links[first].append((second, passage.passage_id))
            links[second].append((first, passage.passage_id))
    return tuple(
        (region_id, tuple(sorted(values)))
        for region_id, values in sorted(links.items())
    )


def _reachable_region(
    point: Point2,
    grid: np.ndarray,
    lattice: Sequence[Point2],
    sample_regions: Sequence[str | None],
    *,
    allowed: frozenset[str] | None = None,
) -> str | None:
    """Nearest labelled sample reachable through the full static ground grid,
    counting only ``allowed`` regions when given."""

    if grid.ndim < 2 or not lattice:
        return None
    height, width = int(grid.shape[0]), int(grid.shape[1])
    targets: dict[tuple[int, int], set[str]] = {}
    for sample, region_id in zip(lattice, sample_regions, strict=True):
        if region_id is not None and (allowed is None or region_id in allowed):
            targets.setdefault((math.floor(sample.x), math.floor(sample.y)), set()).add(
                region_id
            )

    start = (math.floor(point.x), math.floor(point.y))
    if not _pathable(grid, *start):
        pathable = [
            (x, y) for y in range(height) for x in range(width) if _pathable(grid, x, y)
        ]
        if not pathable:
            return None
        start = min(
            pathable,
            key=lambda cell: (
                (cell[0] - point.x) ** 2 + (cell[1] - point.y) ** 2,
                cell[1],
                cell[0],
            ),
        )

    queue = deque([(start, 0)])
    visited = {start}
    found_distance: int | None = None
    found: set[str] = set()
    while queue:
        (x, y), distance = queue.popleft()
        if found_distance is not None and distance > found_distance:
            break
        if labels := targets.get((x, y)):
            found_distance = distance
            found.update(labels)
            continue
        for dx, dy in ((-1, 0), (0, -1), (0, 1), (1, 0)):
            other = (x + dx, y + dy)
            if other not in visited and _pathable(grid, *other):
                visited.add(other)
                queue.append((other, distance + 1))
    return min(found, default=None)


def _nearest_region(
    point: Point2, regions: Mapping[str, tuple[Point2, tuple[int, ...]]]
) -> str | None:
    return min(
        regions,
        key=lambda region_id: (point.distance_to(regions[region_id][0]), region_id),
        default=None,
    )


def _segment_cells(start: Point2, end: Point2) -> Iterator[tuple[int, int]]:
    steps = max(1, math.ceil(start.distance_to(end) * 2.0))
    for step in range(steps + 1):
        fraction = step / steps
        yield (
            math.floor(start.x + (end.x - start.x) * fraction),
            math.floor(start.y + (end.y - start.y) * fraction),
        )


def _straight_step_clear(grid: np.ndarray, start: Point2, end: Point2) -> bool:
    return all(_pathable(grid, x, y) for x, y in _segment_cells(start, end))


def _pathable(grid: np.ndarray, x: int, y: int) -> bool:
    try:
        return (
            0 <= y < grid.shape[0]
            and 0 <= x < grid.shape[1]
            and float(grid[y, x]) > 0.0
        )
    except (IndexError, TypeError, ValueError):
        return False


def _choke_width(choke) -> float | None:
    if bool(_safe_attr(choke, "is_vision_blocker", False)):
        return None
    side_a = _point(_safe_attr(choke, "side_a"))
    side_b = _point(_safe_attr(choke, "side_b"))
    if side_a is None or side_b is None:
        return None
    width = float(side_a.distance_to(side_b))
    if bool(_safe_attr(choke, "is_ramp", False)):
        width += 1.0
    return max(1.0, width)


def _choke_area(choke, cells: frozenset[tuple[int, int]]) -> float:
    try:
        area = float(_safe_attr(choke, "area", 0.0) or 0.0)
    except (TypeError, ValueError):
        area = 0.0
    return max(area, float(len(cells)), _MIN_REGION_AREA)


def _passage_key(
    item: tuple[PassageKind, Point2, float | None, tuple[str, ...], tuple[_Choke, ...]]
) -> tuple:
    kind, position, width, regions, _ = item
    return (kind, regions, *_point_key(position), math.inf if width is None else width)


def _validate(topology: MapTopology, expansions: tuple[Point2, ...]) -> None:
    region_ids = {region.region_id for region in topology.regions}
    if len(region_ids) != len(topology.regions):
        raise ValueError("topology has duplicate region ids")
    if tuple(position for position, _ in topology.expansion_to_region) != expansions:
        raise ValueError(
            "every expansion must have exactly one canonical region mapping"
        )
    if any(
        region_id not in region_ids for _, region_id in topology.expansion_to_region
    ):
        raise ValueError("an expansion references an unknown region")
    for passage in topology.passages:
        if len(passage.regions) < 2 or len(set(passage.regions)) != len(
            passage.regions
        ):
            raise ValueError("passages must connect distinct regions")
        if not set(passage.regions) <= region_ids:
            raise ValueError("a passage references an unknown region")
        if bool(passage.blocker_tags) != (passage.blocker_type is not None):
            raise ValueError("a blocked passage must name its blockers and their kind")
        if passage.state != OPEN and not passage.blocker_tags:
            raise ValueError("only a passage with blockers may be shut")
    for split in topology.region_splits:
        if split.region_id in region_ids or not set(split.into) <= region_ids:
            raise ValueError("a split region must be replaced by known sub-regions")
    reverse = {
        (region_id, neighbour, passage_id)
        for region_id, links in topology.adjacency
        for neighbour, passage_id in links
    }
    if any(
        (neighbour, region_id, passage_id) not in reverse
        for region_id, neighbour, passage_id in reverse
    ):
        raise ValueError("topology adjacency must be symmetric")


def _items(obj, name: str) -> tuple:
    return _iter(_safe_attr(obj, name, ()))


def _iter(value) -> tuple:
    try:
        return tuple(value or ())
    except (RuntimeError, TypeError):
        return ()


def _safe_attr(obj, name: str, default=None):
    try:
        return getattr(obj, name, default)
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return default


def _call_region(function, point):
    if not callable(function):
        return None
    try:
        return function(point)
    except (AttributeError, IndexError, RuntimeError, TypeError, ValueError):
        return None


def _point(value) -> Point2 | None:
    if isinstance(value, Point2):
        return value
    try:
        return Point2((float(value[0]), float(value[1])))
    except (IndexError, TypeError, ValueError):
        return None


def _point_key(point: Point2) -> tuple[float, float]:
    return (round(float(point.x), 6), round(float(point.y), 6))


def _mean(points: Sequence[Point2]) -> Point2 | None:
    if not points:
        return None
    return Point2(
        (
            sum(float(point.x) for point in points) / len(points),
            sum(float(point.y) for point in points) / len(points),
        )
    )

"""Where the free army stands: the staging point that reacts best.

The army no operation needs waits where it answers every base of ours soonest,
in front of them on the enemy's way while building an advantage, on a choke
that guards them if one is at hand, and away from where the enemy is. A choke
is one feature of a good position, not the question.

Candidates are the lattice points of the regions that hold a base of ours and
of their neighbours -- our ground and the ground next to it, pathable by
construction -- but the enemy start region and its neighbours, unless a base
of ours is there: no army stages on the enemy's doorstep. The hold point of a
passage that guards a base -- `setback` cells from it toward the center of the
region behind it, on that region's nearest lattice point -- is one of them,
tagged with the passage.

Distances are ground distances over the `MapTopology`: straight inside a
region, else out through its passages, passage to passage (all pairs, once per
map). D is the one between the two starts; E is the enemy start.

    score = -reaction + choke - exposure

- reaction: sqrt(mean_b (r_b / D)^2) over our bases b, the root mean square
  response. It lies between the mean, which would give up an outlying base,
  and the worst, which would drag the army to it. The response to a base is

      r_b = d(p, b) - advance * max(0, d(E, b) - d(E, p))

  its distance, shortened by how far in front of it the point stands on the
  enemy's way: an enemy coming for b meets the army first. Behind a base the
  response is just its distance. So a passage every approach to our bases
  crosses is good ground without being asked about, and the point settles in
  front of the bases' center by more the more they spread -- it moves out as
  the territory grows, a base at a time, and never to the forward base alone,
  since in front of a base r_b still grows by 1 - advance for every cell. With
  two entrances that share no approach, being behind both costs no more than
  being behind one, and the point between them wins. `advance` is how far
  forward Strategy's posture lets the army stand, which the planner decides:
  0 while defending or recovering, when the point only covers.
- choke: choke_weight * guarded * exp(-width / width_scale), at the hold
  point of a passage: guarded is the share of our bases the enemy start no
  longer reaches with the passage closed -- every approach to them crosses
  it. A border, whose width is unknown, earns none.
- exposure: threat_weight * threat * (1 - support)
  + control_weight * max(0, -control), the Awareness influence field at the
  point: possible enemy combat presence we do not contest, and standing on
  the enemy's side of the field. The field is saturated: it ranks places, it
  measures no fight. Support earns nothing by itself -- at the anchor it is
  mostly the army the anchor holds, and rewarding it would keep the army
  wherever it already stands -- it only answers the enemy where the enemy is.

`evaluate` computes the distances once per map and set of bases; the field is
read every frame. `StagingPolicy` chooses again when a base is taken or lost
or the advance changes, and otherwise keeps the point it holds until
another outscores it by `staging_margin`.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from sc2.position import Point2

from bot.attention import AttentionState, BaseView, MapView
from bot.awareness import InfluenceField

if TYPE_CHECKING:
    from ..planner import MapControlConfig

NO_CANDIDATES = "no_candidates"
NO_ENEMY_ROUTE = "no_enemy_route"

# Why the held point is where it is.
KEPT = "kept"
INITIAL = "initial"
HELD_INVALID = "held_invalid"
BASES_CHANGED = "bases_changed"
POSTURE_CHANGED = "posture_changed"
AWARENESS = "awareness"

# Absorbs float noise so a challenger exactly `staging_margin` ahead counts.
_TOLERANCE = 1e-9


class Ground:
    """Ground distances over one map's topology."""

    def __init__(self, map_view: MapView) -> None:
        topology = map_view.topology
        self.map = map_view
        self._xy = np.array(
            [(passage.position.x, passage.position.y) for passage in topology.passages],
            dtype=float,
        ).reshape(-1, 2)
        members: dict[str, list[int]] = {}
        for index, passage in enumerate(topology.passages):
            for region_id in passage.regions:
                members.setdefault(region_id, []).append(index)
        self._passages = {key: np.array(value, dtype=int) for key, value in members.items()}
        # Passage to passage through the regions they share, then all pairs.
        count = len(topology.passages)
        steps = np.full((count, count), np.inf)
        np.fill_diagonal(steps, 0.0)
        for indices in self._passages.values():
            block = np.ix_(indices, indices)
            steps[block] = np.minimum(steps[block], _gaps(self._xy[indices], self._xy[indices]))
        for middle in range(count):
            steps = np.minimum(steps, steps[:, middle, None] + steps[None, middle, :])
        self._steps = steps
        self.lattice = np.array(
            [(point.x, point.y) for point in map_view.lattice], dtype=float
        ).reshape(-1, 2)
        region_of: list[str | None] = [None] * len(map_view.lattice)
        for region in topology.regions:
            for index in region.sample_indices:
                if 0 <= index < len(region_of):
                    region_of[index] = region.region_id
        self.region_of = tuple(region_of)
        self._owned = np.array(
            [index for index, region in enumerate(region_of) if region is not None], dtype=int
        )
        # The regions the enemy start reaches, and reaches with each passage closed.
        links = dict(topology.adjacency)
        enemy = topology.enemy_start_region
        self.open: frozenset[str] = frozenset() if enemy is None else reached(links, enemy)
        self.cut: dict[str, frozenset[str]] = (
            {}
            if enemy is None
            else {
                passage.passage_id: reached(links, enemy, closed=passage.passage_id)
                for passage in topology.passages
            }
        )

    def locate(self, point: Point2) -> str | None:
        """The region of an expansion, else of the nearest sample that has one."""

        region = self.map.topology.expansion_region(point)
        if region is not None or not len(self._owned):
            return region
        xy = self.lattice[self._owned]
        nearest = int(np.argmin((xy[:, 0] - point.x) ** 2 + (xy[:, 1] - point.y) ** 2))
        return self.region_of[int(self._owned[nearest])]

    def table(self, point: Point2, region_id: str | None) -> np.ndarray:
        """The ground distance from `point`, in `region_id`, to every passage."""

        own = self._passages.get(region_id) if region_id is not None else None
        if own is None:
            return np.full(len(self._xy), np.inf)
        first = np.hypot(self._xy[own, 0] - point.x, self._xy[own, 1] - point.y)
        return (first[:, None] + self._steps[own, :]).min(axis=0)

    def to(
        self,
        xy: np.ndarray,
        region_id: str | None,
        point: Point2,
        point_region: str | None,
        table: np.ndarray,
    ) -> np.ndarray:
        """The ground distance from each of `xy`, all in `region_id`, to
        `point`; `table` is `point`'s."""

        via = self._passages.get(region_id) if region_id is not None else None
        if via is None:
            result = np.full(len(xy), np.inf)
        else:
            result = (_gaps(xy, self._xy[via]) + table[None, via]).min(axis=1)
        if region_id is not None and region_id == point_region:
            result = np.minimum(result, np.hypot(xy[:, 0] - point.x, xy[:, 1] - point.y))
        return result


@dataclass(frozen=True, slots=True, eq=False)
class Candidates:
    """Every staging candidate of one set of bases, by lattice index, with
    what holds until a base is taken or lost."""

    indices: np.ndarray
    xy: np.ndarray
    regions: tuple[str, ...]
    # The guarding passage whose hold point it is.
    passages: tuple[str | None, ...]
    # By candidate and base, in cells: the ground distance, and how far in
    # front of the base the candidate stands on the enemy's way,
    # max(0, d(E, b) - d(E, p)).
    distance: np.ndarray
    lead: np.ndarray
    # mean_b d(E, b) - d(E, p), in cells: in front of our average base, or
    # behind it when negative.
    front: np.ndarray
    choke: np.ndarray
    # D, in cells.
    scale: float
    # By base id.
    bases: tuple[str, ...]

    def response(self, advance: float) -> np.ndarray:
        return self.distance - advance * self.lead

    def position(self, row: int) -> Point2:
        return Point2((float(self.xy[row, 0]), float(self.xy[row, 1])))


def evaluate(
    ground: Ground, bases: Sequence[BaseView], config: MapControlConfig
) -> tuple[Candidates | None, str | None]:
    """The candidates and what holds for them, or why there are none."""

    map_view = ground.map
    topology = map_view.topology
    enemy = topology.enemy_start_region
    if enemy is None:
        return None, NO_ENEMY_ROUTE
    own_region = topology.own_start_region or ground.locate(map_view.own_start)
    from_enemy = ground.table(map_view.enemy_start, enemy)
    scale = float(
        ground.to(_xy(map_view.own_start), own_region, map_view.enemy_start, enemy, from_enemy)[0]
    )
    if not np.isfinite(scale) or scale <= 0.0:
        return None, NO_ENEMY_ROUTE
    home = ground.table(map_view.own_start, own_region)
    # A base the main cannot walk to is covered from nowhere we stand.
    located: list[tuple[BaseView, str, np.ndarray]] = []
    for base in bases:
        region = ground.locate(base.position)
        if region is None:
            continue
        to_home = ground.to(_xy(base.position), region, map_view.own_start, own_region, home)
        if np.isfinite(to_home[0]):
            located.append((base, region, ground.table(base.position, region)))
    if not located:
        return None, NO_CANDIDATES
    # The enemy's way to each base; one it cannot walk to is never in front.
    approach = np.array(
        [
            ground.to(_xy(base.position), region, map_view.enemy_start, enemy, from_enemy)[0]
            for base, region, _ in located
        ]
    )
    walked = np.isfinite(approach)
    if not walked.any():
        return None, NO_ENEMY_ROUTE

    base_regions = {region for _, region, _ in located}
    doorstep = {enemy, *(neighbour for neighbour, _ in topology.neighbours(enemy))}
    relevant = base_regions | {
        neighbour
        for region in base_regions
        for neighbour, _ in topology.neighbours(region)
        if neighbour not in doorstep
    }
    rows = sorted(
        (index, region)
        for index, region in enumerate(ground.region_of)
        if region is not None and region in relevant
    )
    if not rows:
        return None, NO_CANDIDATES
    indices = np.array([index for index, _ in rows], dtype=int)
    regions = tuple(region for _, region in rows)
    xy = ground.lattice[indices]
    distance = np.full((len(rows), len(located)), np.inf)
    to_enemy = np.full(len(rows), np.inf)
    for region in sorted(set(regions)):
        mask = np.array([owner == region for owner in regions])
        for column, (base, base_region, table) in enumerate(located):
            distance[mask, column] = ground.to(xy[mask], region, base.position, base_region, table)
        to_enemy[mask] = ground.to(xy[mask], region, map_view.enemy_start, enemy, from_enemy)
    keep = np.isfinite(distance).all(axis=1) & np.isfinite(to_enemy)
    if not keep.any():
        return None, NO_CANDIDATES
    indices, xy, distance, to_enemy = indices[keep], xy[keep], distance[keep], to_enemy[keep]
    regions = tuple(region for region, kept in zip(regions, keep, strict=True) if kept)

    passages: list[str | None] = [None] * len(indices)
    choke = np.zeros(len(indices))
    row_of = {int(index): row for row, index in enumerate(indices)}
    for passage in topology.passages:
        cut = ground.cut.get(passage.passage_id, ground.open)
        guarded = sum(1 for _, region, _ in located if region in ground.open and region not in cut)
        sides = [region for region in sorted(passage.regions) if region in relevant]
        behind = next((region for region in sides if region not in cut), None)
        if not guarded or behind is None:
            continue
        hold = _hold(map_view, ground, behind, passage.position, config.setback)
        row = None if hold is None else row_of.get(hold)
        if row is None:
            continue
        width = passage.width
        narrow = 0.0 if width is None else float(np.exp(-width / config.width_scale))
        bonus = config.choke_weight * guarded / len(located) * narrow
        if passages[row] is None or bonus > choke[row]:
            passages[row], choke[row] = passage.passage_id, bonus

    ahead = np.where(walked, approach, 0.0)[None, :] - to_enemy[:, None]
    lead = np.where(walked[None, :], np.maximum(0.0, ahead), 0.0)
    return (
        Candidates(
            indices=indices,
            xy=xy,
            regions=regions,
            passages=tuple(passages),
            distance=distance,
            lead=lead,
            front=float(approach[walked].mean()) - to_enemy,
            choke=choke,
            scale=scale,
            bases=tuple(base.base_id for base, _, _ in located),
        ),
        None,
    )


@dataclass(frozen=True, slots=True)
class StagingPoint:
    """One candidate as scored this frame."""

    position: Point2
    region_id: str
    passage_id: str | None
    reaction: float
    # The base answered last and its response, and the mean distance to our
    # bases, in cells.
    worst: float
    worst_base: str
    mean: float
    # In front of our average base on the enemy's way, in cells; negative behind.
    front: float
    choke: float
    threat: float
    support: float
    control: float
    exposure: float
    score: float


@dataclass(frozen=True, slots=True)
class StagingPlan:
    selected: StagingPoint
    # kept, or why the held point last changed: initial, held_invalid,
    # bases_changed, posture_changed or awareness.
    switch: str
    # When the held point was chosen, and the one it replaced.
    since: float
    previous: Point2 | None
    # How much standing in front of a base shortened the response.
    advance: float
    # The best candidate of each region, best first, up to `top_candidates`.
    top: tuple[StagingPoint, ...]
    candidate_count: int
    # D, in cells, and how many bases were covered.
    scale: float
    bases: int


class StagingPolicy:
    def __init__(self, config: MapControlConfig) -> None:
        self.config = config
        self._ground: Ground | None = None
        self._bases: tuple[str, ...] | None = None
        self._candidates: Candidates | None = None
        self._fallback: str | None = None
        # The reaction of every candidate, by posture, for the current bases.
        self._reaction: dict[float, tuple[np.ndarray, np.ndarray]] = {}
        # The lattice index held, since when, and the point it replaced.
        self._held: int | None = None
        self._since = 0.0
        self._previous: Point2 | None = None
        self._advance: float | None = None

    def plan(
        self, attention: AttentionState, field: InfluenceField, advance: float
    ) -> tuple[StagingPlan | None, str | None]:
        bases_changed = self._evaluate(attention)
        candidates = self._candidates
        posture_changed = self._advance is not None and advance != self._advance
        self._advance = advance
        if candidates is None:
            self._held, self._previous = None, None
            return None, self._fallback
        config = self.config
        if advance not in self._reaction:
            response = candidates.response(advance)
            self._reaction[advance] = (
                response,
                np.sqrt(((response / candidates.scale) ** 2).mean(axis=1)),
            )
        response, reaction = self._reaction[advance]
        threat, support, control = _sample(field, candidates.indices, len(attention.map.lattice))
        exposure = config.threat_weight * threat * (1.0 - support) + (
            config.control_weight * np.maximum(0.0, -control)
        )
        score = -reaction + candidates.choke - exposure
        best = int(np.argmax(score))
        rows = np.flatnonzero(candidates.indices == self._held) if self._held is not None else ()
        held = int(rows[0]) if len(rows) else None
        # New bases or a new posture choose again; the field alone must clear the margin.
        settled = not (bases_changed or posture_changed)
        if held is not None and (
            best == held
            or (settled and score[best] < score[held] + config.staging_margin - _TOLERANCE)
        ):
            chosen, switch = held, KEPT
        else:
            chosen = best
            switch = (
                INITIAL
                if self._held is None
                else HELD_INVALID
                if held is None
                else BASES_CHANGED
                if bases_changed
                else POSTURE_CHANGED
                if posture_changed
                else AWARENESS
            )
            if self._held is not None:
                self._previous = self._point_of(self._held)
            self._held, self._since = int(candidates.indices[chosen]), attention.time

        def point(row: int) -> StagingPoint:
            worst = int(np.argmax(response[row]))
            return StagingPoint(
                position=candidates.position(row),
                region_id=candidates.regions[row],
                passage_id=candidates.passages[row],
                reaction=float(reaction[row]),
                worst=float(response[row, worst]),
                worst_base=candidates.bases[worst],
                mean=float(candidates.distance[row].mean()),
                front=float(candidates.front[row]),
                choke=float(candidates.choke[row]),
                threat=float(threat[row]),
                support=float(support[row]),
                control=float(control[row]),
                exposure=float(exposure[row]),
                score=float(score[row]),
            )

        top: list[int] = []
        seen: set[str] = set()
        for row in np.lexsort((candidates.indices, -score)).tolist():
            if candidates.regions[row] in seen:
                continue
            seen.add(candidates.regions[row])
            top.append(row)
            if len(top) == config.top_candidates:
                break
        return (
            StagingPlan(
                selected=point(chosen),
                switch=switch,
                since=self._since,
                previous=self._previous,
                advance=advance,
                top=tuple(point(row) for row in top),
                candidate_count=len(candidates.indices),
                scale=candidates.scale,
                bases=len(candidates.bases),
            ),
            None,
        )

    def _evaluate(self, attention: AttentionState) -> bool:
        """Evaluates the candidates again when the map or our bases change;
        whether they did."""

        map_view = attention.map
        bases = tuple(base.base_id for base in attention.bases)
        if self._ground is not None and self._ground.map is map_view and bases == self._bases:
            return False
        if self._ground is None or self._ground.map is not map_view:
            self._ground = Ground(map_view)
        changed = self._bases is not None
        self._bases = bases
        self._candidates, self._fallback = evaluate(self._ground, attention.bases, self.config)
        self._reaction = {}
        return changed

    def _point_of(self, index: int) -> Point2 | None:
        lattice = self._ground.map.lattice if self._ground is not None else ()
        return lattice[index] if 0 <= index < len(lattice) else None


def _hold(
    map_view: MapView, ground: Ground, region_id: str, position: Point2, setback: float
) -> int | None:
    """The lattice index where the army holds a passage from `region_id`."""

    region = map_view.topology.region(region_id)
    if region is None:
        return None
    samples = [index for index in region.sample_indices if 0 <= index < len(ground.region_of)]
    if not samples:
        return None
    goal = position.towards(region.center, setback, limit=True)
    xy = ground.lattice[samples]
    return samples[int(np.argmin((xy[:, 0] - goal.x) ** 2 + (xy[:, 1] - goal.y) ** 2))]


def reached(
    links: Mapping[str, tuple[tuple[str, str], ...]], start: str, *, closed: str | None = None
) -> frozenset[str]:
    """The regions reached from `start` without crossing the passage `closed`."""

    found = {start}
    frontier = deque([start])
    while frontier:
        for neighbour, passage_id in links.get(frontier.popleft(), ()):
            if passage_id != closed and neighbour not in found:
                found.add(neighbour)
                frontier.append(neighbour)
    return frozenset(found)


def _sample(
    field: InfluenceField, indices: np.ndarray, samples: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """threat, support and control at the candidates; nothing from a field
    that is not read over this lattice."""

    if len(field.positions) != samples:
        empty = np.zeros(len(indices))
        return empty, empty, empty
    return field.threat[indices], field.support[indices], field.control[indices]


def _gaps(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    return np.hypot(first[:, None, 0] - second[None, :, 0], first[:, None, 1] - second[None, :, 1])


def _xy(point: Point2) -> np.ndarray:
    return np.array([(float(point.x), float(point.y))])

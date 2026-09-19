"""Which single passage the free army would hold, read from the static
topology alone: the policy before `staging`, kept beside it for comparison
(`MapControlConfig.policy` picks which one places the anchor). `reached` is
shared: `staging` asks it which bases a passage guards.

A passage is a candidate when it separates: with it closed, some of our bases
the enemy start reaches today can no longer be reached. Its score is

    score = protected + quality - overextension

- protected: `base_value` per base of ours the passage shuts off from the
  enemy start.
- quality: `quality_weight * exp(-width / width_scale)`: a narrow choke is
  held by fewer units. A border, whose width is unknown, earns none, so a
  choke wins over a border that protects as much.
- overextension: `sum(base_value * (1 - exp(-d / L)))` over the bases it
  protects, d the distance from the passage to the base and
  `L = reach_share * D`, D the distance between the two starts: a base is
  protected less the farther from it the army stands, as the army takes that
  much longer to come back to it. `protected - overextension` stays below
  `protected`, and above 0.

A passage that separates nothing protects nothing and is no candidate. The
passages next to the enemy start separate all of our bases -- they cut the
enemy off from the whole map -- and overextension is what keeps them from
winning: it grows with every base such a passage claims from afar, so a
forward passage only wins where it is not much farther from what it shuts
off than a passage nearer home.

The anchor is where the army stands to hold the passage: `setback` cells from
it toward the center of the region on our side, snapped to the nearest lattice
point of that region, so it is pathable and on our side.

Nothing here reads Awareness.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sc2.position import Point2

from bot.attention import BaseView, MapView

if TYPE_CHECKING:
    from .planner import MapControlConfig


@dataclass(frozen=True, slots=True)
class PassageCandidate:
    passage_id: str
    kind: str
    position: Point2
    # The region on our side of the passage, where the army stands.
    region_id: str
    # By base id.
    protected_bases: tuple[str, ...]
    protected: float
    quality: float
    overextension: float

    @property
    def score(self) -> float:
        return self.protected + self.quality - self.overextension


def candidates(
    map_view: MapView, bases: Sequence[BaseView], config: MapControlConfig
) -> tuple[PassageCandidate, ...]:
    """Every passage that separates a base of ours from the enemy start, best
    first; ties by passage id."""

    topology = map_view.topology
    enemy = topology.enemy_start_region
    if enemy is None:
        return ()
    owned = [
        (base, region)
        for base in bases
        if (region := topology.expansion_region(base.position)) is not None
    ]
    links: Mapping[str, tuple[tuple[str, str], ...]] = dict(topology.adjacency)
    # A base the enemy cannot reach by ground today is shut off by no passage.
    open_map = reached(links, enemy)
    owned = [(base, region) for base, region in owned if region in open_map]
    if not owned:
        return ()
    reach = config.reach_share * max(1.0, map_view.own_start.distance_to(map_view.enemy_start))
    found: list[PassageCandidate] = []
    for passage in topology.passages:
        cut = reached(links, enemy, closed=passage.passage_id)
        protected = [base for base, region in owned if region not in cut]
        side = next((region for region in passage.regions if region not in cut), None)
        if not protected or side is None:
            continue
        found.append(
            PassageCandidate(
                passage_id=passage.passage_id,
                kind=passage.kind,
                position=passage.position,
                region_id=side,
                protected_bases=tuple(base.base_id for base in protected),
                protected=config.base_value * len(protected),
                quality=(
                    0.0
                    if passage.width is None
                    else config.quality_weight * math.exp(-passage.width / config.width_scale)
                ),
                overextension=sum(
                    config.base_value
                    * (1.0 - math.exp(-base.position.distance_to(passage.position) / reach))
                    for base in protected
                ),
            )
        )
    return tuple(sorted(found, key=lambda candidate: (-candidate.score, candidate.passage_id)))


def anchor_of(map_view: MapView, candidate: PassageCandidate, setback: float) -> Point2 | None:
    """Where the army stands to hold the passage; None without a lattice point
    in the region on our side."""

    region = map_view.topology.region(candidate.region_id)
    if region is None:
        return None
    lattice = map_view.lattice
    points = [lattice[index] for index in region.sample_indices if 0 <= index < len(lattice)]
    if not points:
        return None
    goal = candidate.position.towards(region.center, setback, limit=True)
    return min(points, key=lambda point: (point.distance_to(goal), point.x, point.y))


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

"""Gives enemy force clusters an identity that carries across updates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sc2.position import Point2

from ..heuristics import EnemyForceHeuristics, main_force_score
from ..knowledge import EnemySighting
from .cluster import EnemyForceAwareness, EnemyForceCluster
from .clustering import centroid, group_by_proximity, summarize


@dataclass(frozen=True, slots=True)
class _Track:
    """What identity needs to remember about one reported cluster."""

    cluster_id: int
    center: Point2
    unit_tags: frozenset[int]
    reported_at: float


class EnemyForceTracker:
    """Turns remembered enemy combat sightings into tracked force clusters.

    Clusters are regrouped from scratch on every update; only their ids carry
    over. A new cluster takes the id of the previous cluster it shares the
    most units with, or else of an unclaimed one reported within
    ``match_radius`` of it. A cluster that disappears keeps its id reserved
    for ``identity_memory`` seconds, for that matching only: it is never
    reported again, so a cluster still lives exactly as long as Awareness
    remembers any of its units.
    """

    def __init__(self, config: EnemyForceHeuristics | None = None) -> None:
        self.config = config or EnemyForceHeuristics()
        self._reported: tuple[_Track, ...] = ()
        self._departed: tuple[_Track, ...] = ()
        self._next_id = 1

    def update(
        self, sightings: Sequence[EnemySighting], *, now: float
    ) -> EnemyForceAwareness:
        config = self.config
        groups = group_by_proximity(
            tuple(sighting for sighting in sightings if sighting.is_combat_unit),
            config.link_radius,
        )
        candidates = (
            *self._reported,
            *(
                track
                for track in self._departed
                if now - track.reported_at <= config.identity_memory
            ),
        )
        ids = self._identify(groups, candidates)
        clusters = tuple(
            sorted(
                (
                    summarize(group, cluster_id=cluster_id, now=now, config=config)
                    for group, cluster_id in zip(groups, ids, strict=True)
                ),
                key=lambda cluster: (-cluster.combat_strength, cluster.cluster_id),
            )
        )

        reported_ids = set(ids)
        self._departed = tuple(
            track for track in candidates if track.cluster_id not in reported_ids
        )
        self._reported = tuple(
            _Track(
                cluster_id=cluster.cluster_id,
                center=cluster.center,
                unit_tags=frozenset(cluster.unit_tags),
                reported_at=now,
            )
            for cluster in clusters
        )
        return EnemyForceAwareness(clusters=clusters, main=self._main_force(clusters))

    def _identify(
        self,
        groups: Sequence[Sequence[EnemySighting]],
        candidates: Sequence[_Track],
    ) -> list[int]:
        assigned: dict[int, int] = {}
        claimed: set[int] = set()

        # Shared units are the strongest evidence of being the same cluster.
        overlaps: list[tuple[int, int, int]] = []
        for index, group in enumerate(groups):
            tags = frozenset(sighting.tag for sighting in group)
            for track in candidates:
                if shared := len(tags & track.unit_tags):
                    overlaps.append((shared, track.cluster_id, index))
        overlaps.sort(key=lambda item: (-item[0], item[1], item[2]))
        for _, cluster_id, index in overlaps:
            if index not in assigned and cluster_id not in claimed:
                assigned[index] = cluster_id
                claimed.add(cluster_id)

        # Otherwise a group showing up where an unclaimed cluster just was
        # takes over its id. Larger groups choose first.
        for index in sorted(range(len(groups)), key=lambda i: (-len(groups[i]), i)):
            if index in assigned:
                continue
            center = centroid(groups[index])
            nearest = min(
                (
                    (track.center.distance_to(center), track.cluster_id)
                    for track in candidates
                    if track.cluster_id not in claimed
                ),
                default=None,
            )
            if nearest is not None and nearest[0] <= self.config.match_radius:
                assigned[index] = nearest[1]
            else:
                assigned[index] = self._next_id
                self._next_id += 1
            claimed.add(assigned[index])
        return [assigned[index] for index in range(len(groups))]

    def _main_force(
        self, clusters: tuple[EnemyForceCluster, ...]
    ) -> EnemyForceCluster | None:
        config = self.config
        return max(
            clusters,
            key=lambda cluster: (
                main_force_score(cluster.combat_strength, cluster.confidence, config),
                cluster.confidence,
                -cluster.cluster_id,
            ),
            default=None,
        )

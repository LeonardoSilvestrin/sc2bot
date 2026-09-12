from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from sc2.position import Point2


@dataclass(frozen=True, slots=True)
class EnemyForceCluster:
    """One believed concentration of enemy combat units.

    Built from remembered sightings, not only what is in vision this frame:
    ``center`` and ``radius`` describe where its units were last seen, and
    ``position_uncertainty`` how far the group may have moved since. The
    strengths are what was seen, in supply (see ``enemy/heuristics.py``), so
    they compare directly with ``ArmyBelief`` and our own army supply; they
    never decay with age. ``confidence`` alone says how much they still
    describe the present.
    """

    cluster_id: int
    center: Point2
    radius: float
    position_uncertainty: float
    combat_strength: float
    anti_air_strength: float
    anti_ground_strength: float
    unit_count: int
    visible_unit_count: int
    unit_tags: tuple[int, ...]
    last_observed_at: float | None
    confidence: float

    def distance_to(self, position: Point2) -> float:
        """Distance from ``position`` to the nearest place the group may be."""

        return max(
            0.0,
            self.center.distance_to(position)
            - self.radius
            - self.position_uncertainty,
        )


@dataclass(frozen=True, slots=True)
class EnemyForceAwareness:
    """Every enemy force cluster Awareness believes in, strongest first."""

    clusters: tuple[EnemyForceCluster, ...] = field(default_factory=tuple)
    main: EnemyForceCluster | None = None

    def get(self, cluster_id: int) -> EnemyForceCluster | None:
        return next(
            (item for item in self.clusters if item.cluster_id == cluster_id), None
        )

    def near(
        self, position: Point2, distance: float = 0.0
    ) -> tuple[EnemyForceCluster, ...]:
        """Clusters that may be within ``distance`` of ``position``, nearest first.

        Reach includes each cluster's spread and how far it may have moved
        since it was last seen, so a stale cluster is "possibly near" over a
        wider area than a fresh one.
        """

        return tuple(
            sorted(
                (
                    cluster
                    for cluster in self.clusters
                    if cluster.confidence > 0.0
                    and cluster.distance_to(position) <= distance
                ),
                key=lambda cluster: (cluster.distance_to(position), cluster.cluster_id),
            )
        )

    def __iter__(self) -> Iterator[EnemyForceCluster]:
        return iter(self.clusters)

    def __len__(self) -> int:
        return len(self.clusters)

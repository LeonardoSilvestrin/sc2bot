from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from time import perf_counter

from sc2.position import Point2

from bot.ports.logging import BotLogger
from bot.world.attention import MapPassage, MapRegion, WorldFacts

from ..bases import BaseAwareness
from ..enemy import EnemyAwareness
from ..spatial import SpatialField
from ..spatial.kernel import cadence_due, same_version
from .config import TerritoryConfig
from .frontline import frontline
from .influence import (
    InfluenceSources,
    classify,
    friendly_forces,
    mean_confidence,
    read_point,
)
from .model import (
    BaseTerritory,
    PassageTerritory,
    RegionTerritory,
    TerritoryControl,
    TerritoryReading,
    TerritorySample,
    TerritorySnapshot,
)
from .observation import ObservationMemory
from .topology import TerritoryTopology, build_topology, ground_access

COMPONENT = "world.awareness.territory"


@dataclass(slots=True)
class TerritoryAssessor:
    """Derives the territory reading on a strategic cadence.

    Its parts live at different rates. ``TerritoryTopology`` -- region
    membership, the passage graph, enemy origins, lattice neighbours -- is
    rebuilt only when the map topology changes version (identity first,
    equality as the fallback, as in ``SpatialFieldModel``). What we see is
    remembered every frame. Influence, classification, the frontline and
    ground access are recomputed once per ``update_interval``; in between
    the previous snapshot is returned as is.
    """

    config: TerritoryConfig = field(default_factory=TerritoryConfig)
    logger: BotLogger | None = None
    updates: int = field(default=0, init=False)
    topology_rebuilds: int = field(default=0, init=False)
    last_update_ms: float = field(default=0.0, init=False)
    _topology: TerritoryTopology | None = field(default=None, init=False, repr=False)
    _snapshot: TerritorySnapshot | None = field(default=None, init=False, repr=False)
    _observations: ObservationMemory = field(
        default_factory=ObservationMemory, init=False, repr=False
    )
    _updated_at: float | None = field(default=None, init=False, repr=False)
    _points_source: tuple[Point2, ...] | None = field(
        default=None, init=False, repr=False
    )
    _regions_source: tuple[MapRegion, ...] | None = field(
        default=None, init=False, repr=False
    )
    _passages_source: tuple[MapPassage, ...] | None = field(
        default=None, init=False, repr=False
    )
    _starts_source: tuple[Point2, ...] | None = field(
        default=None, init=False, repr=False
    )
    _spacing: float | None = field(default=None, init=False, repr=False)
    _last_perf_logged_at: float | None = field(default=None, init=False, repr=False)

    def update(
        self,
        world: WorldFacts,
        *,
        spatial: SpatialField,
        bases: BaseAwareness,
        enemy: EnemyAwareness,
    ) -> TerritorySnapshot:
        rebuilt = self._refresh_topology(world, spatial)
        assert self._topology is not None
        if rebuilt:
            self._observations.reset(len(self._topology.points))
        # Every frame, so a glimpse between two updates still counts.
        self._observations.record(world.map.pathable_visibility, world.time)
        if (
            not rebuilt
            and self._snapshot is not None
            and not cadence_due(
                world.time, self._updated_at, self.config.update_interval
            )
        ):
            return self._snapshot

        started = perf_counter()
        # Hysteresis follows each place's previous class; a new topology
        # re-indexes every place, so it starts over.
        previous = None if rebuilt else self._snapshot
        sources = InfluenceSources(
            friendly_forces=friendly_forces(world.own_units, self.config),
            friendly_sites=tuple(base.position for base in bases),
            enemy_forces=enemy.forces.clusters,
            enemy_sites=tuple(
                (base.position, base.confidence) for base in enemy.bases.confirmed
            ),
        )
        snapshot = self._assess(world, self._topology, bases, sources, previous)
        self._snapshot = snapshot
        self._updated_at = world.time
        self.updates += 1
        self.last_update_ms = (perf_counter() - started) * 1000.0
        self._maybe_log_performance(world.time, snapshot, sources)
        return snapshot

    def _refresh_topology(self, world: WorldFacts, spatial: SpatialField) -> bool:
        map_facts = world.map
        valid = (
            self._topology is not None
            and same_version(map_facts.pathable_points, self._points_source)
            and same_version(map_facts.regions, self._regions_source)
            and same_version(map_facts.passages, self._passages_source)
            and same_version(map_facts.enemy_starts, self._starts_source)
            and spatial.sample_spacing == self._spacing
        )
        # Adopt an equal rebuilt value so the next check is identity again.
        self._points_source = map_facts.pathable_points
        self._regions_source = map_facts.regions
        self._passages_source = map_facts.passages
        self._starts_source = map_facts.enemy_starts
        if valid:
            return False
        self._spacing = spatial.sample_spacing
        self._topology = build_topology(
            tuple(sample.position for sample in spatial.samples),
            spatial.sample_spacing,
            map_facts,
        )
        self.topology_rebuilds += 1
        return True

    def _assess(
        self,
        world: WorldFacts,
        topology: TerritoryTopology,
        bases: BaseAwareness,
        sources: InfluenceSources,
        previous: TerritorySnapshot | None,
    ) -> TerritorySnapshot:
        config = self.config
        now = world.time
        stale_after = config.observation_stale_after
        observations = self._observations
        samples_before = () if previous is None else previous.samples
        regions_before = () if previous is None else previous.regions
        passages_before = () if previous is None else previous.passages

        samples = tuple(
            TerritorySample(
                position=point,
                reading=read_point(
                    point,
                    sources,
                    config,
                    _previous_control(samples_before, index),
                    observations.quality(index, now, stale_after),
                ),
                region=topology.sample_regions[index],
            )
            for index, point in enumerate(topology.points)
        )
        region_readings = tuple(
            self._region_reading(
                region,
                tuple(
                    samples[member].reading for member in topology.region_samples[index]
                ),
                sources,
                _previous_control(regions_before, index),
                observations.quality(topology.center_samples[index], now, stale_after),
            )
            for index, region in enumerate(topology.regions)
        )
        passage_readings = tuple(
            read_point(
                passage.position,
                sources,
                config,
                _previous_control(passages_before, index),
                observations.quality(topology.passage_samples[index], now, stale_after),
            )
            for index, passage in enumerate(topology.passages)
        )

        # Regions are the first nodes of the access graph, passages follow.
        node_readings = (*region_readings, *passage_readings)
        enemy_presence = [reading.enemy_influence for reading in node_readings]
        for origin in topology.origins:
            enemy_presence[origin] = max(
                enemy_presence[origin], config.enemy_origin_strength
            )
        passes = [1.0 - reading.hold for reading in node_readings]
        region_count = len(region_readings)
        # Passages are the barriers; the layered walk, where regions block
        # too, is kept alongside for comparison in shadow mode.
        access = ground_access(
            topology.adjacency,
            enemy_presence,
            [1.0] * region_count + passes[region_count:],
        )
        layered_access = ground_access(topology.adjacency, enemy_presence, passes)

        regions = tuple(
            RegionTerritory(
                key=region.key,
                center=region.center,
                expansions=region.expansions,
                reading=region_readings[index],
                ground_access=access[index],
                layered_ground_access=layered_access[index],
            )
            for index, region in enumerate(topology.regions)
        )
        by_key = {region.key: region for region in regions}
        return TerritorySnapshot(
            samples=samples,
            regions=regions,
            passages=tuple(
                PassageTerritory(
                    key=passage.key,
                    position=passage.position,
                    regions=passage.regions,
                    reading=passage_readings[index],
                )
                for index, passage in enumerate(topology.passages)
            ),
            bases=tuple(
                BaseTerritory(
                    base_id=base.base_id,
                    position=base.position,
                    region=(
                        None
                        if (key := topology.locate(base.position)) is None
                        else by_key.get(key)
                    ),
                )
                for base in bases
            ),
            frontline=frontline(samples, topology.edges),
            confidence=mean_confidence(tuple(sample.reading for sample in samples)),
            updated_at=now,
        )

    def _region_reading(
        self,
        region: MapRegion,
        members: tuple[TerritoryReading, ...],
        sources: InfluenceSources,
        previous: TerritoryControl | None,
        observation: float,
    ) -> TerritoryReading:
        """A region reads as the mean of its samples, unwatched ones included;
        one too small to hold a sample reads at its centre."""

        if not members:
            return read_point(
                region.center, sources, self.config, previous, observation
            )
        count = len(members)
        return classify(
            friendly=sum(reading.friendly_influence for reading in members) / count,
            enemy=sum(reading.enemy_influence for reading in members) / count,
            confidence=mean_confidence(members),
            config=self.config,
            previous=previous,
            friendly_military=sum(reading.friendly_military for reading in members)
            / count,
            friendly_ground_denial=sum(
                reading.friendly_ground_denial for reading in members
            )
            / count,
        )

    def _maybe_log_performance(
        self, now: float, snapshot: TerritorySnapshot, sources: InfluenceSources
    ) -> None:
        if self.logger is None:
            return
        if (
            self._last_perf_logged_at is not None
            and 0.0
            <= now - self._last_perf_logged_at
            < self.config.perf_heartbeat_interval
        ):
            return
        self._last_perf_logged_at = now
        self.logger.event(
            "territory.perf",
            component=COMPONENT,
            game_time=now,
            data={
                "update_ms": round(self.last_update_ms, 4),
                "updates": self.updates,
                "topology_rebuilds": self.topology_rebuilds,
                "samples": len(snapshot.samples),
                "regions": len(snapshot.regions),
                "passages": len(snapshot.passages),
                "friendly_forces": len(sources.friendly_forces),
                "enemy_forces": len(sources.enemy_forces),
            },
        )


def _previous_control(
    items: Sequence[TerritorySample | RegionTerritory | PassageTerritory],
    index: int,
) -> TerritoryControl | None:
    if index >= len(items):
        return None
    return items[index].control

"""Rank regions by creep presence, control and exposure."""

from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState

from .field import InfluenceField

TUMORS = frozenset(
    {UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORBURROWED, UnitTypeId.CREEPTUMORQUEEN}
)


@dataclass(frozen=True, slots=True)
class RegionControl:
    region_id: str
    target: Point2
    creep: float
    threat: float
    control: float
    score: float
    creep_points: tuple[Point2, ...] = ()


def rank_regions(attention: AttentionState, influence: InfluenceField) -> tuple[RegionControl, ...]:
    """Safe creep fronts first; unseen tumors are located by the creep grid.

    The target is a creep sample on our side of the region, rather than its
    centre, so a cleaner peels the front instead of crossing it to get there.
    """
    result = []
    for region in attention.map.topology.regions:
        samples = [attention.map.lattice[i] for i in region.sample_indices]
        creeping = [point for point in samples if attention.has_creep(point)]
        creeping.extend(
            unit.position
            for unit in attention.enemy_structures
            if unit.type_id in TUMORS and attention.map.region_at(unit.position) == region.region_id
        )
        indices = [i for i in region.sample_indices if i < len(influence.positions)]
        threat = float(influence.threat[indices].max()) if indices else 0.0
        control = float(influence.control[indices].mean()) if indices else 0.0
        points = tuple(
            sorted(set(creeping), key=lambda p: (p.distance_to(attention.map.own_start), p.x, p.y))
        )
        target = points[0] if points else region.center
        coverage = min(1.0, len(creeping) / max(1, len(samples)))
        result.append(
            RegionControl(
                region.region_id,
                target,
                coverage,
                threat,
                control,
                coverage + control - 2.0 * threat,
                points,
            )
        )
    return tuple(sorted(result, key=lambda r: (-r.score, r.region_id)))

"""Where Strategy wants control, derived from what Awareness describes.

Awareness says where control exists: region security, passage holds, who
dominates a region, how well we know it. This policy says where control is
wanted, how much, and why -- as ``ControlObjective``\\ s. It never says who
goes, where exactly a unit stands, or at what mission priority.

    held bases     one BASE objective each: the base's stake, how structurally
                   exposed it is, which way the enemy is, and enemy presence
    passages       the ways into each held base's region, importance inherited
                   from the base they protect (an entrance to the outside keeps
                   all of it, a link between two held bases a share)
    approaches     the regions one passage outside our own, wanted as control
                   (intent.map_control, enemy reachability) or as information
                   (intent.information, how little we know them)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sc2.position import Point2

from bot.world.awareness import AwarenessSnapshot, PassageTerritory, RegionTerritory

from ..intent import StrategicActivity, StrategicIntent
from .config import SpatialPolicyConfig
from .model import ControlObjective, ControlTargetKind, SpatialStrategySnapshot


@dataclass(frozen=True, slots=True)
class _HeldBase:
    base_id: str
    position: Point2
    is_main: bool
    threat_score: float
    region: RegionTerritory | None


def derive_control_objectives(
    intent: StrategicIntent,
    awareness: AwarenessSnapshot,
    config: SpatialPolicyConfig | None = None,
) -> SpatialStrategySnapshot:
    """Every control objective the intent asks for, most important first."""

    config = config or SpatialPolicyConfig()
    held = _held_bases(awareness)
    own_regions = frozenset(
        base.region.key for base in held if base.region is not None
    )
    links = _links(awareness.territory.passages)
    enemy = _enemy_points(awareness)

    bases = _base_objectives(intent, held, own_regions, links, enemy, config)
    passages = _passage_objectives(
        intent, held, bases, own_regions, links, enemy, config
    )
    areas = _area_objectives(intent, awareness, own_regions, links, config)
    objectives = sorted(
        (
            item
            for item in (*bases.values(), *passages, *areas)
            if item.importance >= config.minimum_importance
        ),
        key=lambda item: (-item.importance, item.objective_id),
    )
    return SpatialStrategySnapshot(
        objectives=tuple(objectives), updated_at=awareness.updated_at
    )


def _base_objectives(
    intent: StrategicIntent,
    held: tuple[_HeldBase, ...],
    own_regions: frozenset[str],
    links: Mapping[str, tuple[PassageTerritory, ...]],
    enemy: tuple[Point2, ...],
    config: SpatialPolicyConfig,
) -> dict[str, ControlObjective]:
    facing = _facing({base.base_id: _nearest(base.position, enemy) for base in held})
    desired = _raised(config.base_control_floor, intent.defense)
    objectives: dict[str, ControlObjective] = {}
    for base in held:
        exposure = _exposure(base, own_regions, links, config)
        threat = _clamp01(base.threat_score / config.full_threat_score)
        stake = 1.0 if base.is_main else config.expansion_stake
        region = base.region
        objectives[base.base_id] = ControlObjective(
            objective_id=f"base:{base.base_id}",
            kind=ControlTargetKind.BASE,
            target_key=base.base_id,
            position=base.position,
            activity=StrategicActivity.DEFENSE,
            desired_control=desired,
            desired_visibility=0.0,
            importance=_clamp01(
                intent.defense
                * stake
                * _raised(config.exposure_floor, exposure)
                * _raised(config.facing_floor, facing[base.base_id])
                + config.threat_weight * threat
            ),
            current_control=(
                1.0 - threat if region is None else _clamp01(region.ground_security)
            ),
            current_visibility=(
                1.0 if region is None else _clamp01(region.reading.confidence)
            ),
            reason=_base_reason(base, exposure, threat),
            region_key=None if region is None else region.key,
        )
    return objectives


def _passage_objectives(
    intent: StrategicIntent,
    held: tuple[_HeldBase, ...],
    bases: Mapping[str, ControlObjective],
    own_regions: frozenset[str],
    links: Mapping[str, tuple[PassageTerritory, ...]],
    enemy: tuple[Point2, ...],
    config: SpatialPolicyConfig,
) -> tuple[ControlObjective, ...]:
    chosen: dict[str, ControlObjective] = {}
    for base in held:
        if base.region is None:
            continue
        protected = bases[base.base_id]
        options = links.get(base.region.key, ())
        facing = _facing({item.key: _nearest(item.position, enemy) for item in options})
        ranked: list[ControlObjective] = []
        for passage in options:
            external = _other_region(passage, base.region.key) not in own_regions
            ranked.append(
                ControlObjective(
                    objective_id=f"passage:{passage.key}",
                    kind=ControlTargetKind.PASSAGE,
                    target_key=passage.key,
                    position=passage.position,
                    activity=StrategicActivity.DEFENSE,
                    desired_control=min(
                        1.0, protected.desired_control + config.passage_control_bonus
                    ),
                    desired_visibility=(
                        intent.information * config.entrance_visibility
                        if external
                        else 0.0
                    ),
                    importance=_clamp01(
                        protected.importance
                        * (1.0 if external else config.internal_passage_share)
                        * _raised(config.facing_floor, facing[passage.key])
                    ),
                    current_control=_clamp01(passage.reading.hold),
                    current_visibility=_clamp01(passage.reading.confidence),
                    reason=(
                        f"entrance_to_{base.base_id}"
                        if external
                        else f"internal_link_of_{base.base_id}"
                    ),
                    region_key=base.region.key,
                    protects=protected.objective_id,
                )
            )
        ranked.sort(key=lambda item: (-item.importance, item.objective_id))
        for item in ranked[: config.max_passages_per_base]:
            current = chosen.get(item.objective_id)
            if current is None or item.importance > current.importance:
                chosen[item.objective_id] = item
    return tuple(chosen.values())


def _area_objectives(
    intent: StrategicIntent,
    awareness: AwarenessSnapshot,
    own_regions: frozenset[str],
    links: Mapping[str, tuple[PassageTerritory, ...]],
    config: SpatialPolicyConfig,
) -> tuple[ControlObjective, ...]:
    territory = awareness.territory
    enemy_regions = frozenset(
        region.key
        for base in awareness.enemy.bases.confirmed
        if (region := territory.region_at(base.position)) is not None
    )
    approaches = sorted(
        {
            other
            for key in own_regions
            for passage in links.get(key, ())
            if (other := _other_region(passage, key)) not in own_regions
            and other not in enemy_regions
        }
    )
    objectives: list[ControlObjective] = []
    for key in approaches:
        region = territory.region(key)
        if region is None:
            continue
        control_value = intent.map_control * _clamp01(region.ground_access)
        information_value = intent.information * (
            1.0 - _clamp01(region.reading.confidence)
        )
        contest = control_value >= information_value
        objectives.append(
            ControlObjective(
                objective_id=f"region:{key}",
                kind=ControlTargetKind.REGION,
                target_key=key,
                position=region.center,
                activity=(
                    StrategicActivity.MAP_CONTROL
                    if contest
                    else StrategicActivity.INFORMATION
                ),
                desired_control=_clamp01(intent.map_control * config.area_control),
                desired_visibility=_clamp01(
                    intent.information * config.area_visibility
                ),
                importance=_clamp01(
                    config.area_weight * max(control_value, information_value)
                ),
                current_control=_clamp01(region.reading.dominance),
                current_visibility=_clamp01(region.reading.confidence),
                reason="contested_approach" if contest else "uncertain_approach",
                region_key=key,
            )
        )
    objectives.sort(key=lambda item: (-item.importance, item.objective_id))
    return tuple(objectives[: config.max_area_objectives])


def _held_bases(awareness: AwarenessSnapshot) -> tuple[_HeldBase, ...]:
    # Held bases arrive in the game's townhall order, which is not stable
    # between frames; objectives must not reorder with it.
    regions = {item.base_id: item.region for item in awareness.territory.bases}
    return tuple(
        sorted(
            (
                _HeldBase(
                    base_id=base.base_id,
                    position=base.position,
                    is_main=base.is_main,
                    threat_score=max(0.0, base.threat_score),
                    region=regions.get(base.base_id),
                )
                for base in awareness.bases
            ),
            key=lambda base: base.base_id,
        )
    )


def _links(
    passages: tuple[PassageTerritory, ...],
) -> dict[str, tuple[PassageTerritory, ...]]:
    links: dict[str, list[PassageTerritory]] = {}
    for passage in sorted(passages, key=lambda item: item.key):
        for key in set(passage.regions):
            links.setdefault(key, []).append(passage)
    return {key: tuple(items) for key, items in links.items()}


def _other_region(passage: PassageTerritory, key: str) -> str:
    first, second = passage.regions
    return second if first == key else first


def _exposure(
    base: _HeldBase,
    own_regions: frozenset[str],
    links: Mapping[str, tuple[PassageTerritory, ...]],
    config: SpatialPolicyConfig,
) -> float:
    """1.0 when any way into the base's region comes from outside our bases."""

    if base.region is None or base.region.key not in links:
        return config.unknown_exposure
    outside = any(
        _other_region(passage, base.region.key) not in own_regions
        for passage in links[base.region.key]
    )
    return 1.0 if outside else config.interior_exposure


def _enemy_points(awareness: AwarenessSnapshot) -> tuple[Point2, ...]:
    points = tuple(base.position for base in awareness.enemy.bases.confirmed)
    if points:
        return points
    main = awareness.enemy.location("enemy_main")
    return () if main is None else (main.position,)


def _nearest(position: Point2, points: tuple[Point2, ...]) -> float | None:
    return min((position.distance_to(point) for point in points), default=None)


def _facing(distances: Mapping[str, float | None]) -> dict[str, float]:
    """1.0 for whatever is nearest the enemy, less the farther the rest are."""

    known = [value for value in distances.values() if value is not None]
    if not known:
        return {key: 1.0 for key in distances}
    nearest = min(known)
    return {
        key: 1.0 if value is None else (nearest + 1.0) / (value + 1.0)
        for key, value in distances.items()
    }


def _base_reason(base: _HeldBase, exposure: float, threat: float) -> str:
    kind = "main" if base.is_main else "expansion"
    if threat > 0.0:
        return f"threatened_{kind}"
    if base.region is None:
        return f"{kind}_without_topology"
    return f"exposed_{kind}" if exposure >= 1.0 else f"sheltered_{kind}"


def _raised(floor: float, value: float) -> float:
    return floor + (1.0 - floor) * _clamp01(value)


def _clamp01(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


__all__ = ["derive_control_objectives"]

"""Both sides' influence at a point, and what it says about who holds it."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from sc2.position import Point2

from bot.world.attention import UnitSnapshot

from ..enemy.forces.clustering import group_by_proximity
from ..spatial.kernel import (
    ForcePresence,
    distance_squared,
    force_influence,
    kernel_squared,
    saturate,
)
from .config import TerritoryConfig
from .model import TerritoryControl, TerritoryReading


@dataclass(frozen=True, slots=True)
class FriendlyForce:
    """One group of our own combat units.

    Shaped like ``EnemyForceCluster`` so both sides spread influence through
    the same ``force_influence``. Our units are seen now and exactly where
    they are, so a friendly force never drifts and is always certain.
    """

    center: Point2
    radius: float
    combat_strength: float
    unit_count: int
    position_uncertainty: float = 0.0
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class InfluenceSources:
    """Everything that projects territorial influence during one update."""

    friendly_forces: tuple[ForcePresence, ...] = ()
    # Our townhalls.
    friendly_sites: tuple[Point2, ...] = ()
    enemy_forces: tuple[ForcePresence, ...] = ()
    # Confirmed enemy bases, each weighted by how current that belief is.
    enemy_sites: tuple[tuple[Point2, float], ...] = ()


def friendly_forces(
    units: Iterable[UnitSnapshot], config: TerritoryConfig
) -> tuple[FriendlyForce, ...]:
    """Group our combat units -- never workers -- as enemy clusters are.

    Strength is supply, as for enemy clusters, so both sides compare directly.
    """

    combat = tuple(
        unit
        for unit in units
        if not unit.is_worker and (unit.can_attack_ground or unit.can_attack_air)
    )
    forces: list[FriendlyForce] = []
    for group in group_by_proximity(
        combat, config.friendly_link_radius, position_of=_position
    ):
        center = Point2(
            (
                sum(unit.position.x for unit in group) / len(group),
                sum(unit.position.y for unit in group) / len(group),
            )
        )
        forces.append(
            FriendlyForce(
                center=center,
                radius=max(center.distance_to(unit.position) for unit in group),
                combat_strength=sum(
                    unit.supply_cost
                    if unit.supply_cost > 0.0
                    else config.zero_supply_unit_value
                    for unit in group
                ),
                unit_count=len(group),
            )
        )
    return tuple(forces)


def read_point(
    point: Point2,
    sources: InfluenceSources,
    config: TerritoryConfig,
    previous: TerritoryControl | None = None,
) -> TerritoryReading:
    """The territory reading at one point.

    Each side's military and infrastructure contributions add up raw and
    saturate once, so neither kind of presence double-counts the other. Our
    army's part is also kept on its own: only an army blocks ground passage.
    """

    military_raw, _ = force_influence(
        point,
        sources.friendly_forces,
        sigma=config.military_sigma,
        full_strength=config.full_strength,
    )
    friendly_raw = military_raw
    for site in sources.friendly_sites:
        friendly_raw += _site_influence(point, site, 1.0, config)
    enemy_raw, enemy_confidence = force_influence(
        point,
        sources.enemy_forces,
        sigma=config.military_sigma,
        full_strength=config.full_strength,
    )
    for site, weight in sources.enemy_sites:
        enemy_raw += _site_influence(point, site, weight, config)
    friendly, enemy = saturate(friendly_raw), saturate(enemy_raw)
    return classify(
        friendly=friendly,
        enemy=enemy,
        confidence=reading_confidence(friendly, enemy, enemy_confidence),
        config=config,
        previous=previous,
        friendly_military=saturate(military_raw),
    )


def dominance(friendly: float, enemy: float, epsilon: float) -> float:
    """``(F - E) / (F + E + epsilon)``: -1 enemy, 0 balanced or empty, +1 ours."""

    return (friendly - enemy) / (friendly + enemy + epsilon)


def reading_confidence(friendly: float, enemy: float, enemy_confidence: float) -> float:
    """Our side is always current; the reading is as current as its enemy share."""

    total = friendly + enemy
    if total <= 0.0:
        return enemy_confidence
    return (friendly + enemy * enemy_confidence) / total


def weighted_confidence(readings: Sequence[TerritoryReading]) -> float:
    """Confidence over several readings, each weighted by its presence."""

    weight = sum(reading.presence for reading in readings)
    if weight > 0.0:
        return (
            sum(reading.presence * reading.confidence for reading in readings) / weight
        )
    if readings:
        return sum(reading.confidence for reading in readings) / len(readings)
    return 1.0


def classify(
    *,
    friendly: float,
    enemy: float,
    confidence: float,
    config: TerritoryConfig,
    previous: TerritoryControl | None = None,
    friendly_military: float = 0.0,
) -> TerritoryReading:
    """Name who holds a place from both influences and the confidence.

    Too little combined presence is UNCONTROLLED, however lopsided the
    dominance: 0.001 against nothing holds nothing. Otherwise a side needs
    ``control_dominance`` -- raised as confidence falls -- or the place is
    CONTESTED. ``previous`` shifts each threshold by ``hysteresis`` in favour
    of the class the place already had.
    """

    reading = TerritoryReading(
        friendly_influence=friendly,
        enemy_influence=enemy,
        dominance=dominance(friendly, enemy, config.dominance_epsilon),
        confidence=confidence,
        friendly_military=friendly_military,
    )
    # Falling under the presence floor enters UNCONTROLLED.
    if reading.presence < config.min_presence - _shift(
        TerritoryControl.UNCONTROLLED, previous, config.hysteresis
    ):
        return reading
    required = config.control_dominance + config.uncertainty_margin * (
        1.0 - max(0.0, min(1.0, confidence))
    )
    if reading.dominance >= required + _shift(
        TerritoryControl.FRIENDLY, previous, config.hysteresis
    ):
        control = TerritoryControl.FRIENDLY
    elif -reading.dominance >= required + _shift(
        TerritoryControl.ENEMY, previous, config.hysteresis
    ):
        control = TerritoryControl.ENEMY
    else:
        control = TerritoryControl.CONTESTED
    return replace(reading, control=control)


def _shift(
    target: TerritoryControl, previous: TerritoryControl | None, hysteresis: float
) -> float:
    """How much harder (+) or easier (-) being ``target`` is than the bare
    threshold: easier to stay in the class a place has, harder to enter
    another."""

    if previous is None:
        return 0.0
    return -hysteresis if previous is target else hysteresis


def _site_influence(
    point: Point2, site: Point2, weight: float, config: TerritoryConfig
) -> float:
    return (
        weight
        * config.infrastructure_weight
        * kernel_squared(distance_squared(point, site), config.infrastructure_sigma)
    )


def _position(unit: UnitSnapshot) -> Point2:
    return unit.position

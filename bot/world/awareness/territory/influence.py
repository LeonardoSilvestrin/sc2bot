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
from .model import FriendlyForce, TerritoryControl, TerritoryReading


@dataclass(frozen=True, slots=True)
class InfluenceSources:
    """Everything that projects territorial influence during one update."""

    friendly_forces: tuple[FriendlyForce, ...] = ()
    # Our townhalls.
    friendly_sites: tuple[Point2, ...] = ()
    enemy_forces: tuple[ForcePresence, ...] = ()
    # Confirmed enemy bases, each with how current that belief is.
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
        values = tuple(
            (
                unit,
                unit.supply_cost
                if unit.supply_cost > 0.0
                else config.zero_supply_unit_value,
            )
            for unit in group
        )
        forces.append(
            FriendlyForce(
                center=center,
                radius=max(center.distance_to(unit.position) for unit in group),
                combat_strength=sum(value for _, value in values),
                anti_ground_strength=sum(
                    value for unit, value in values if unit.can_attack_ground
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
    observation: float = 0.0,
) -> TerritoryReading:
    """The territory reading at one point.

    Each side's military and infrastructure contributions add up raw and
    saturate once, so neither kind of presence double-counts the other. Our
    army's part is also kept alone, twice: all of it as military presence,
    and what can fight ground units as ground denial. ``observation`` is how
    fresh our last look at the point is (see ``reading_confidence``).
    """

    military = force_influence(
        point,
        sources.friendly_forces,
        sigma=config.military_sigma,
        full_strength=config.full_strength,
    )
    ground = force_influence(
        point,
        sources.friendly_forces,
        sigma=config.military_sigma,
        full_strength=config.full_strength,
        ground_only=True,
    )
    friendly_raw = military.raw
    for site in sources.friendly_sites:
        friendly_raw += _site_influence(point, site, config)
    enemy = force_influence(
        point,
        sources.enemy_forces,
        sigma=config.military_sigma,
        full_strength=config.full_strength,
    )
    enemy_raw, evidence = enemy.raw, enemy.evidence
    for site, site_confidence in sources.enemy_sites:
        reach = _site_influence(point, site, config)
        enemy_raw += reach * site_confidence
        evidence += reach
    return classify(
        friendly=saturate(friendly_raw),
        enemy=saturate(enemy_raw),
        confidence=reading_confidence(
            observation=observation, known=enemy_raw, evidence=evidence, config=config
        ),
        config=config,
        previous=previous,
        friendly_military=saturate(military.raw),
        friendly_ground_denial=saturate(ground.raw),
    )


def dominance(friendly: float, enemy: float, epsilon: float) -> float:
    """``(F - E) / (F + E + epsilon)``: -1 enemy, 0 balanced or empty, +1 ours."""

    return (friendly - enemy) / (friendly + enemy + epsilon)


def reading_confidence(
    *, observation: float, known: float, evidence: float, config: TerritoryConfig
) -> float:
    """How well we know the enemy side of a reading, 0..1.

    Our side is always known, so this is about the enemy alone. A look at a
    place shows what is there, nothing included: ``observation`` is how
    fresh our last look is. Without one, only remembered enemy sources speak
    for the place: ``known / (evidence + undetected_presence)`` is their raw
    influence as still believed, against what it would be were every one
    current plus the enemy we may simply not have seen. So unwatched empty
    space reads 0 -- no known enemy is not knowing there is none -- a kernel
    tail vouches for nearly nothing, and a half-believed base for less than
    half. The better of the two is kept: two stale clues never add up to a
    fresh one.
    """

    remembered = known / (evidence + config.undetected_presence)
    return max(0.0, min(1.0, max(observation, remembered)))


def mean_confidence(readings: Sequence[TerritoryReading]) -> float:
    """How well we know several places at once: unwatched ones count too."""

    if not readings:
        return 0.0
    return sum(reading.confidence for reading in readings) / len(readings)


def classify(
    *,
    friendly: float,
    enemy: float,
    confidence: float,
    config: TerritoryConfig,
    previous: TerritoryControl | None = None,
    friendly_military: float = 0.0,
    friendly_ground_denial: float = 0.0,
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
        friendly_ground_denial=friendly_ground_denial,
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


def _site_influence(point: Point2, site: Point2, config: TerritoryConfig) -> float:
    """A townhall's raw reach at ``point``, before any confidence."""

    return config.infrastructure_weight * kernel_squared(
        distance_squared(point, site), config.infrastructure_sigma
    )


def _position(unit: UnitSnapshot) -> Point2:
    return unit.position

"""The tunable numbers behind the enemy base and force models.

Every weight here is a first, deliberately small guess -- supply stands in
for fighting value, linear decay for forgetting, a clamp for "enough" --
kept in one module so it can be read, argued with and retuned without
touching how bases are assessed (``bases/assessor.py``) or how forces are
grouped and tracked (``forces/``). Nothing here knows a race or a unit type.

Values and strengths describe what was last known and never decay with its
age; freshness only ever feeds a confidence. The one place the two are
combined is ``main_force_score``, itself an inference.
"""

from __future__ import annotations

from dataclasses import dataclass

from .knowledge import EnemySighting


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def freshness(age: float, stale_after: float) -> float:
    """1.0 for evidence seen this instant, decaying linearly to 0 by ``stale_after``.

    """

    if stale_after <= 0.0:
        return 0.0
    return clamp01(1.0 - max(0.0, age) / stale_after)


def _from_floor(floor: float, fraction: float) -> float:
    """``floor`` when ``fraction`` is 0, rising linearly to 1.0 when it is 1."""

    return floor + (1.0 - floor) * clamp01(fraction)


def _require_positive(config: object, *names: str) -> None:
    for name in names:
        if getattr(config, name) <= 0.0:
            raise ValueError(f"{name} must be positive")


def _require_non_negative(config: object, *names: str) -> None:
    for name in names:
        if getattr(config, name) < 0.0:
            raise ValueError(f"{name} must not be negative")


def _require_unit_interval(config: object, *names: str) -> None:
    for name in names:
        if not 0.0 <= getattr(config, name) <= 1.0:
            raise ValueError(f"{name} must be within [0, 1]")


# --- combat value: what one enemy sighting is worth in a fight -------------


@dataclass(frozen=True, slots=True)
class CombatValueWeights:
    """Fighting value in supply, so it compares directly with ``ArmyBelief``."""

    # Mobile combat units are worth their supply. The few that fight for no
    # supply (interceptors, broodlings, locusts) still count a little.
    zero_supply_unit_value: float = 0.25
    # A weaponed structure (cannon, spore, spine, turret, fortress) has no
    # supply; each reads as about two supply of army.
    static_defense_value: float = 2.0

    def __post_init__(self) -> None:
        _require_positive(self, "zero_supply_unit_value", "static_defense_value")


@dataclass(frozen=True, slots=True)
class CombatValue:
    total: float = 0.0
    anti_air: float = 0.0
    anti_ground: float = 0.0


def combat_value(sighting: EnemySighting, weights: CombatValueWeights) -> CombatValue:
    """A fighter counts in full toward every domain it can attack.

    Workers, weaponless casters and weaponless structures (bunker, shield
    battery) are worth nothing here.
    """

    if sighting.is_combat_unit:
        total = (
            sighting.supply_cost
            if sighting.supply_cost > 0.0
            else weights.zero_supply_unit_value
        )
    elif sighting.is_static_defense:
        total = weights.static_defense_value
    else:
        return CombatValue()
    return CombatValue(
        total=total,
        anti_air=total if sighting.can_attack_air else 0.0,
        anti_ground=total if sighting.can_attack_ground else 0.0,
    )


# --- enemy bases -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnemyBaseHeuristics:
    # Which remembered sightings belong to a base slot.
    worker_radius: float = 10.0  # mineral line and geysers
    defense_radius: float = 12.0  # static defense and the units guarding it

    # economic value = presence_weight + worker_weight * saturation
    presence_weight: float = 0.4
    worker_weight: float = 0.6
    saturated_workers: float = 16.0

    # defense = min(1, sum of defender values / full_*_defense)
    full_air_defense: float = 8.0
    full_ground_defense: float = 8.0
    # How long a defender reading takes to go fully stale (confidence 0).
    # Units walk away, so theirs matches the ~30 s Ares remembers them for;
    # structures stay put and stay credible for much longer.
    unit_defense_stale_after: float = 30.0
    structure_defense_stale_after: float = 180.0

    combat: CombatValueWeights = CombatValueWeights()

    def __post_init__(self) -> None:
        _require_positive(
            self,
            "worker_radius",
            "defense_radius",
            "saturated_workers",
            "full_air_defense",
            "full_ground_defense",
            "unit_defense_stale_after",
            "structure_defense_stale_after",
        )
        _require_unit_interval(self, "presence_weight", "worker_weight")
        if self.presence_weight + self.worker_weight > 1.0:
            raise ValueError("presence_weight + worker_weight must not exceed 1")


def economic_value(
    *, confirmed: bool, workers: int, config: EnemyBaseHeuristics
) -> float:
    """Economic value of one base slot as last known, 0..1.

    Only a confirmed base is worth anything. Its presence alone is worth
    ``presence_weight``; the workers last counted there add up to
    ``worker_weight`` at saturation. How old that knowledge is stays out of
    it -- that is the slot's ``confidence``.
    """

    if not confirmed:
        return 0.0
    saturation = clamp01(workers / config.saturated_workers)
    return config.presence_weight + config.worker_weight * saturation


def defender_freshness(
    sighting: EnemySighting, *, now: float, config: EnemyBaseHeuristics
) -> float:
    """How much a remembered defender still describes the present, 0..1."""

    if not sighting.last_seen_known:
        return 0.0

    stale_after = (
        config.structure_defense_stale_after
        if sighting.is_structure
        else config.unit_defense_stale_after
    )
    return freshness(now - sighting.last_seen_at, stale_after)


def defense_score(value: float, full_value: float) -> float:
    return clamp01(value / full_value)


# --- enemy forces ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnemyForceHeuristics:
    # Two combat units this close belong to the same cluster (single linkage).
    link_radius: float = 7.0
    # Confidence reaches 0 here: the window Ares remembers an out-of-vision
    # unit for, so a cluster fades out as its units are being forgotten.
    stale_after: float = 30.0
    # position uncertainty = min(max, drift_speed * strength-weighted age)
    drift_speed: float = 3.0
    max_position_uncertainty: float = 30.0
    # Identity: a cluster sharing no unit with a previous one may still take
    # over the id of one reported within match_radius of it. A cluster that
    # disappears keeps its id reserved for identity_memory seconds.
    match_radius: float = 12.0
    identity_memory: float = 15.0
    # main-force score = strength * (floor .. 1, by confidence): a large army
    # seen a while ago still outranks a small, freshly seen detachment.
    main_force_confidence_floor: float = 0.35

    combat: CombatValueWeights = CombatValueWeights()

    def __post_init__(self) -> None:
        _require_positive(self, "link_radius", "stale_after", "match_radius")
        _require_non_negative(
            self, "drift_speed", "max_position_uncertainty", "identity_memory"
        )
        _require_unit_interval(self, "main_force_confidence_floor")


def position_uncertainty(mean_age: float, config: EnemyForceHeuristics) -> float:
    return min(
        config.max_position_uncertainty, max(0.0, mean_age) * config.drift_speed
    )


def main_force_score(
    strength: float, confidence: float, config: EnemyForceHeuristics
) -> float:
    return strength * _from_floor(config.main_force_confidence_floor, confidence)

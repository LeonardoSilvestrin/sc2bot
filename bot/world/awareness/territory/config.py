from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TerritoryConfig:
    """Every tunable number behind the territory reading, in one place.

    First, deliberately small guesses, kept together so they can be read and
    retuned without touching how influence, classification or ground access
    are computed. See ``_botdev/architecture/territory.md``.
    """

    # Territory is strategic information: recomputed on this cadence, and
    # reused unchanged in between.
    update_interval: float = 1.0

    # --- influence ---------------------------------------------------------
    # A force of this much supply standing on a point reads there as raw
    # influence 1 (saturated 0.63); the same scale as the spatial threat.
    full_strength: float = 8.0
    # How far a force projects control, before its own radius and -- for
    # an enemy cluster -- its position uncertainty widen it.
    military_sigma: float = 12.0
    # Our combat units this close belong to one force (single linkage), as
    # for enemy clusters.
    friendly_link_radius: float = 7.0
    # A combat unit with no supply cost still counts a little, as for enemy
    # clusters.
    zero_supply_unit_value: float = 0.25
    # A townhall is presence, not an army: its raw influence where it
    # stands, and how far that reaches. Enemy bases scale it by confidence.
    infrastructure_weight: float = 0.6
    infrastructure_sigma: float = 14.0

    # --- classification ----------------------------------------------------
    dominance_epsilon: float = 1e-6
    # Below this much combined influence nobody holds a place: UNCONTROLLED.
    min_presence: float = 0.2
    # The |dominance| that names a side, at full confidence ...
    control_dominance: float = 0.4
    # ... raised by up to this much as confidence falls, so an uncertain
    # mixed reading stays CONTESTED instead of naming a side.
    uncertainty_margin: float = 0.3
    # A reading keeps its class until it is past a threshold by this much.
    hysteresis: float = 0.05

    # --- ground access -----------------------------------------------------
    # Enemy start regions always send enemy ground forces, scouted or not.
    enemy_origin_strength: float = 1.0

    perf_heartbeat_interval: float = 10.0

    def __post_init__(self) -> None:
        for name in (
            "full_strength",
            "military_sigma",
            "friendly_link_radius",
            "zero_supply_unit_value",
            "infrastructure_weight",
            "infrastructure_sigma",
            "dominance_epsilon",
            "perf_heartbeat_interval",
        ):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if self.update_interval < 0.0:
            raise ValueError("update_interval must not be negative")
        for name in (
            "min_presence",
            "control_dominance",
            "uncertainty_margin",
            "hysteresis",
            "enemy_origin_strength",
        ):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")
        if self.hysteresis >= min(self.min_presence, self.control_dominance):
            raise ValueError("hysteresis must be below every threshold it shifts")

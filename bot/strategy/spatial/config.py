from __future__ import annotations

import math
from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class SpatialPolicyConfig:
    """Every number behind where Strategy wants control.

    First guesses, like the rest of Strategy's weights. Importance never
    reads how firmly we already hold a place -- our own army would otherwise
    lower the importance of whatever it stands on -- only structure (which
    bases face the outside, which way the enemy is) and enemy presence.
    """

    # --- bases ---------------------------------------------------------------
    # A non-main base's stake relative to the main.
    expansion_stake: float = 0.9
    # Share of a base's importance that remains however sheltered it is ...
    exposure_floor: float = 0.45
    # ... where a base whose every passage leads into another held base is
    # this exposed, one with any passage to the outside fully exposed, and
    # one with no region graph this exposed.
    interior_exposure: float = 0.4
    unknown_exposure: float = 0.7
    # Share of importance the base (or passage) farthest from the enemy keeps
    # against the one nearest.
    facing_floor: float = 0.7
    # Enemy combat presence at a base raises its importance regardless of
    # the defense preference, reaching full weight at this threat score.
    threat_weight: float = 0.3
    full_threat_score: float = 4.0
    # Desired control of a base: this floor, rising with intent.defense.
    base_control_floor: float = 0.5

    # --- passages --------------------------------------------------------
    # Importance share of a passage between two held bases (the entrance to
    # the outside keeps all of it).
    internal_passage_share: float = 0.35
    # A way in is held a little more firmly than the base it guards.
    passage_control_bonus: float = 0.05
    # Desired visibility of an entrance, scaled by intent.information.
    entrance_visibility: float = 0.6
    max_passages_per_base: int = 3

    # --- approaches ------------------------------------------------------
    area_weight: float = 0.9
    # Desired control and visibility of an approach region, scaled by
    # intent.map_control and intent.information respectively.
    area_control: float = 0.65
    area_visibility: float = 0.95
    max_area_objectives: int = 4

    # Objectives less important than this are not worth listing.
    minimum_importance: float = 0.05

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, int) and not isinstance(value, bool):
                if value < 0:
                    raise ValueError(f"{item.name} must not be negative")
                continue
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{item.name} must be finite and not negative")
        for name in (
            "expansion_stake",
            "exposure_floor",
            "interior_exposure",
            "unknown_exposure",
            "facing_floor",
            "threat_weight",
            "base_control_floor",
            "internal_passage_share",
            "passage_control_bonus",
            "entrance_visibility",
            "area_weight",
            "area_control",
            "area_visibility",
            "minimum_importance",
        ):
            if getattr(self, name) > 1.0:
                raise ValueError(f"{name} must be within [0, 1]")
        if self.full_threat_score <= 0.0:
            raise ValueError("full_threat_score must be positive")


__all__ = ["SpatialPolicyConfig"]

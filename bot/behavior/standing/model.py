"""Types local to the standing army behavior."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions.models import MissionKind
from bot.world.awareness.bases import BaseAssessment

# Same roster DefensePlanner treats as combat-capable; kept independent
# (rather than imported) so the two behaviors' unit lists can diverge later
# without coupling them. Banshees are deliberately absent: they belong to
# the specialized harass squad, which would otherwise have to preempt the
# standing army for its own units every time one is produced.
_DEFAULT_COMBAT_TYPES: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.MARINE,
        UnitTypeId.MARAUDER,
        UnitTypeId.REAPER,
        UnitTypeId.SIEGETANK,
        UnitTypeId.SIEGETANKSIEGED,
    }
)


class CombatPosture(Enum):
    """How defensively the standing army should currently be arranged.

    This is deliberately a different axis from ``MacroPosture``:
    ``MacroPosture`` is economic/strategic policy (how risky spending is
    right now); ``CombatPosture`` is only about where standing military
    force should sit when nothing more urgent (``DEFENSE``, harass, ...)
    needs it. Mixing the two would conflate "should I greed for a fourth
    base" with "should my army be forward or home", which are genuinely
    different questions answered from different evidence.
    """

    TURTLE = auto()
    BALANCED = auto()
    PRESSURE = auto()


@dataclass(frozen=True, slots=True)
class StandingConfig:
    """Thresholds for the standing army behavior.

    The core army's priority stays below ``MAP_CONTROL`` (40) and every
    active tactical mission, so a standing slot is always freely
    preemptible. Ratios and the anchor fraction are deliberately small,
    deterministic policy knobs rather than a composition system.
    """

    proposal_cadence: float = 5.0
    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: _DEFAULT_COMBAT_TYPES
    )
    minimum_unit_health: float = 0.0
    mission_timeout: float = 3600.0
    cooldown_seconds: float = 5.0
    commitment_seconds: float = 2.0
    arrival_radius: float = 4.0
    # Share of eligible combat units the core army holds. The remainder is
    # the roaming share, which `MapControlPlanner` claims -- this behavior
    # does not command it, it only leaves room for it.
    core_fraction: float = 0.8
    anchor_fraction_to_newest_base: float = 0.72

    priority: int = 20

    def __post_init__(self) -> None:
        if self.proposal_cadence <= 0.0:
            raise ValueError("proposal_cadence must be positive")
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.mission_timeout <= 0.0:
            raise ValueError("mission_timeout must be positive")
        if self.cooldown_seconds < 0.0:
            raise ValueError("cooldown_seconds must not be negative")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")
        if self.arrival_radius <= 0.0:
            raise ValueError("arrival_radius must be positive")
        if not 0.0 < self.core_fraction <= 1.0:
            raise ValueError("core_fraction must be between 0 and 1")
        if not 0.0 <= self.anchor_fraction_to_newest_base <= 1.0:
            raise ValueError("anchor_fraction_to_newest_base must be between 0 and 1")
        if not 0 <= self.priority <= 100:
            raise ValueError("priority must be between 0 and 100")

    @property
    def roaming_fraction(self) -> float:
        return round(1.0 - self.core_fraction, 4)


@dataclass(frozen=True, slots=True)
class StandingAssessment:
    """Where our army is, what it is protecting, and what is pressing it."""

    now: float
    posture: CombatPosture
    # Held bases ordered by distance from the main -- our stand-in for
    # expansion order until construction timestamps exist.
    bases: tuple[BaseAssessment, ...]
    threatened_base_ids: tuple[str, ...]
    pressure: int
    eligible_units: int
    own_start: Point2

    @property
    def newest_base(self) -> Point2 | None:
        return self.bases[-1].position if self.bases else None

    @property
    def previous_base(self) -> Point2 | None:
        return self.bases[-2].position if len(self.bases) >= 2 else None

    def log_fields(self) -> dict[str, Any]:
        return {
            "posture": self.posture.name,
            "bases": len(self.bases),
            "threatened_bases": list(self.threatened_base_ids),
            "pressure": self.pressure,
            "eligible_units": self.eligible_units,
        }


@dataclass(frozen=True, slots=True)
class StandingPlan:
    """Where the heart of the army should sit, and how much of it."""

    anchor: Point2
    anchor_reason: str
    core_count: int
    core_fraction: float
    roaming_fraction: float
    priority: int

    def log_fields(self) -> dict[str, Any]:
        return {
            "anchor": [round(float(self.anchor.x), 1), round(float(self.anchor.y), 1)],
            "anchor_reason": self.anchor_reason,
            "core_count": self.core_count,
            "core_fraction": self.core_fraction,
            "roaming_fraction": self.roaming_fraction,
            "priority": self.priority,
        }


MISSION_KIND = MissionKind.HOLD_RALLY
SQUAD_ID = "main_army"
DEDUPLICATION_KEY = "hold_rally:main_army"

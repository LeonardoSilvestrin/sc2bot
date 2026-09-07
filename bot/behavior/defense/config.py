from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId

_DEFAULT_DEFENDER_TYPES: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.MARINE,
        UnitTypeId.MARAUDER,
        UnitTypeId.REAPER,
        UnitTypeId.SIEGETANK,
        UnitTypeId.SIEGETANKSIEGED,
        UnitTypeId.BANSHEE,
    }
)


@dataclass(frozen=True, slots=True)
class DefensePlannerConfig:
    """Thresholds for defense proposals, one per threatened base."""

    proposal_cadence: float = 5.0
    threatened_priority: int = 85
    critical_priority: int = 95
    mission_timeout: float = 120.0
    failure_cooldown: float = 10.0
    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: _DEFAULT_DEFENDER_TYPES
    )
    minimum_units: int = 1
    max_desired_units: int = 6
    minimum_unit_health: float = 0.3
    commitment_seconds: float = 3.0

    def __post_init__(self) -> None:
        if self.proposal_cadence <= 0.0:
            raise ValueError("proposal_cadence must be positive")
        if not 0 <= self.threatened_priority <= 100:
            raise ValueError("threatened_priority must be between 0 and 100")
        if not 0 <= self.critical_priority <= 100:
            raise ValueError("critical_priority must be between 0 and 100")
        if self.critical_priority < self.threatened_priority:
            raise ValueError("critical_priority must be >= threatened_priority")
        if self.mission_timeout <= 0.0:
            raise ValueError("mission_timeout must be positive")
        if self.failure_cooldown < 0.0:
            raise ValueError("failure_cooldown must not be negative")
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if self.minimum_units < 1:
            raise ValueError("minimum_units must be at least 1")
        if self.max_desired_units < self.minimum_units:
            raise ValueError("max_desired_units must be >= minimum_units")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId


@dataclass(frozen=True, slots=True)
class HarassPlannerConfig:
    """Thresholds for the first worker-line harass vertical slice."""

    target_key: str = "enemy_natural"
    minimum_workers: int = 16
    proposal_cadence: float = 45.0
    priority: int = 60
    mission_timeout: float = 60.0
    failure_cooldown: float = 30.0
    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: frozenset({UnitTypeId.REAPER})
    )
    minimum_unit_health: float = 0.5
    commitment_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.target_key.strip():
            raise ValueError("target_key must not be empty")
        if self.proposal_cadence <= 0.0:
            raise ValueError("proposal_cadence must be positive")
        if self.minimum_workers < 1:
            raise ValueError("minimum_workers must be at least 1")
        if not 0 <= self.priority <= 100 or self.mission_timeout <= 0.0:
            raise ValueError("invalid priority or mission timeout")
        if self.failure_cooldown < 0.0:
            raise ValueError("failure_cooldown must not be negative")
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")


@dataclass(frozen=True, slots=True)
class BansheeHarassPlannerConfig:
    """Thresholds for the cloaked Banshee harass vertical slice.

    A flying, cloaked harasser cannot be threatened by a ground-only
    defender, so ``minimum_workers`` aside, this deliberately withholds on a
    narrower signal than ``HarassPlannerConfig``'s "any enemy unit visible
    anywhere" -- see ``BansheeHarassPlanner``.
    """

    target_key: str = "enemy_natural"
    minimum_workers: int = 12
    proposal_cadence: float = 45.0
    priority: int = 62
    mission_timeout: float = 70.0
    failure_cooldown: float = 30.0
    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: frozenset({UnitTypeId.BANSHEE})
    )
    minimum_unit_health: float = 0.5
    commitment_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not self.target_key.strip():
            raise ValueError("target_key must not be empty")
        if self.proposal_cadence <= 0.0:
            raise ValueError("proposal_cadence must be positive")
        if self.minimum_workers < 1:
            raise ValueError("minimum_workers must be at least 1")
        if not 0 <= self.priority <= 100 or self.mission_timeout <= 0.0:
            raise ValueError("invalid priority or mission timeout")
        if self.failure_cooldown < 0.0:
            raise ValueError("failure_cooldown must not be negative")
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")

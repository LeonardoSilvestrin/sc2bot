from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId

# Same roster DefensePlanner treats as combat-capable; kept independent
# (rather than imported) so the two planners' unit lists can diverge later
# without coupling them.
_DEFAULT_COMBAT_TYPES: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.MARINE,
        UnitTypeId.MARAUDER,
        UnitTypeId.REAPER,
        UnitTypeId.SIEGETANK,
        UnitTypeId.SIEGETANKSIEGED,
    }
)


@dataclass(frozen=True, slots=True)
class DispositionPlannerConfig:
    """Thresholds for the standing army-disposition planner.

    The main squad's priority stays below ``MAP_CONTROL`` (40) and active
    tactical work. Ratios and the rally fraction are deliberately small,
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
    main_army_ratio: float = 0.8
    rally_fraction_to_newest_expansion: float = 0.72

    main_priority: int = 20

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
        if not 0.0 < self.main_army_ratio <= 1.0:
            raise ValueError("main_army_ratio must be between 0 and 1")
        if not 0.0 <= self.rally_fraction_to_newest_expansion <= 1.0:
            raise ValueError(
                "rally_fraction_to_newest_expansion must be between 0 and 1"
            )
        priorities = (self.main_priority,)
        if any(not 0 <= priority <= 100 for priority in priorities):
            raise ValueError("priorities must be between 0 and 100")

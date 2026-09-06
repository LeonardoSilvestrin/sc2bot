from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId

from bot.attention.models import UnitSnapshot


@dataclass(frozen=True, slots=True)
class UnitRequirement:
    """Unit needs declared by a proposal and enforced by the allocator."""

    unit_types: frozenset[UnitTypeId]
    desired: int
    minimum: int
    flying: bool | None = None
    minimum_health: float = 0.0
    require_ready: bool = True
    exclude_resource_carriers: bool = False
    exclude_constructors: bool = False
    require_available: bool = True

    def __post_init__(self) -> None:
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if self.minimum < 0 or self.desired <= 0 or self.minimum > self.desired:
            raise ValueError("expected 0 <= minimum <= desired and desired > 0")
        if not 0.0 <= self.minimum_health <= 1.0:
            raise ValueError("minimum_health must be between 0 and 1")

    def matches(self, unit: UnitSnapshot, *, check_availability: bool = True) -> bool:
        return (
            self.matches_identity(unit)
            and unit.health_percentage >= self.minimum_health
            and (not self.require_ready or unit.is_ready)
            and (not self.exclude_resource_carriers or not unit.is_carrying_resource)
            and (not self.exclude_constructors or not unit.is_constructing)
            and (
                not check_availability
                or not self.require_available
                or unit.available_for_mission
            )
        )

    def matches_identity(self, unit: UnitSnapshot) -> bool:
        """Stable constraints used to retain an existing mission lease."""

        return unit.unit_type in self.unit_types and (
            self.flying is None or unit.is_flying == self.flying
        )

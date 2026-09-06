from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId

from bot.attention.models import UnitSnapshot


@dataclass(frozen=True, slots=True)
class UnitRequirement:
    """Public request shared by actions and the central unit allocator."""

    unit_types: frozenset[UnitTypeId]
    desired: int
    minimum: int
    flying: bool | None = None

    def __post_init__(self) -> None:
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if self.minimum < 0 or self.desired <= 0 or self.minimum > self.desired:
            raise ValueError("expected 0 <= minimum <= desired and desired > 0")

    def matches(self, unit: UnitSnapshot) -> bool:
        return unit.unit_type in self.unit_types and (
            self.flying is None or unit.is_flying == self.flying
        )

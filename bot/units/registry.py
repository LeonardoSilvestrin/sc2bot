from __future__ import annotations

from dataclasses import dataclass

from bot.attention.models import UnitSnapshot
from bot.contracts.allocation import UnitRequirement


@dataclass(frozen=True, slots=True)
class AllocationResult:
    assigned_tags: tuple[int, ...]
    requirements_satisfied: bool


class UnitRegistry:
    """Central authority for action-to-unit ownership."""

    def __init__(self) -> None:
        self._units: dict[int, UnitSnapshot] = {}
        self._owners: dict[int, str] = {}

    def sync(self, units: tuple[UnitSnapshot, ...]) -> None:
        self._units = {unit.tag: unit for unit in units}
        alive = set(self._units)
        self._owners = {
            tag: owner for tag, owner in self._owners.items() if tag in alive
        }

    def owner_of(self, unit_tag: int) -> str | None:
        return self._owners.get(unit_tag)

    def assigned_to(self, action_id: str) -> tuple[UnitSnapshot, ...]:
        return tuple(
            self._units[tag]
            for tag, owner in self._owners.items()
            if owner == action_id and tag in self._units
        )

    def allocate(
        self, action_id: str, requirements: tuple[UnitRequirement, ...]
    ) -> AllocationResult:
        assigned: list[int] = []
        satisfied = True
        for requirement in requirements:
            existing = [
                unit
                for unit in self.assigned_to(action_id)
                if requirement.matches(unit)
            ]
            needed = max(0, requirement.desired - len(existing))
            available = sorted(
                (
                    unit
                    for unit in self._units.values()
                    if unit.tag not in self._owners and requirement.matches(unit)
                ),
                key=lambda unit: unit.tag,
            )
            for unit in available[:needed]:
                self._owners[unit.tag] = action_id
            total = len(existing) + min(needed, len(available))
            if total < requirement.minimum:
                satisfied = False
            assigned.extend(unit.tag for unit in self.assigned_to(action_id))

        return AllocationResult(
            assigned_tags=tuple(sorted(set(assigned))),
            requirements_satisfied=satisfied,
        )

    def release_action(self, action_id: str) -> None:
        self._owners = {
            tag: owner for tag, owner in self._owners.items() if owner != action_id
        }

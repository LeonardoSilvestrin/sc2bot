"""Why a capability-based mission holds the units it holds.

Scoring every unit every frame would bury the one line worth reading, so this
only speaks when the answer changes: the mission's composition by unit type
moved (which includes a unit type it never had before), or no unit the bot
owns fits its role at all.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from bot.domain import Capability, capabilities_for, score_unit_for_requirement
from bot.engine.missions.models import UnitRequirement
from bot.world.attention import UnitSnapshot


class CapabilityAllocationLog:
    def __init__(self) -> None:
        self._compositions: dict[str, dict[str, int]] = {}
        self._without_candidates: set[str] = set()

    def observe(
        self,
        *,
        mission_id: str,
        requirement: UnitRequirement,
        assigned: tuple[UnitSnapshot, ...],
        own_units: tuple[UnitSnapshot, ...],
    ) -> list[tuple[str, dict[str, Any]]]:
        """The events this allocation is worth, as (name, data) pairs."""

        capability = requirement.capability
        if capability is None:
            return []
        events: list[tuple[str, dict[str, Any]]] = []

        composition = dict(
            sorted(Counter(unit.unit_type.name for unit in assigned).items())
        )
        previous = self._compositions.get(mission_id, {})
        if composition != previous:
            self._compositions[mission_id] = composition
            events.append(
                (
                    "capability_composition_changed",
                    {
                        "role": capability.name,
                        "previous_composition": previous,
                        "composition": composition,
                        "new_unit_types": sorted(set(composition) - set(previous)),
                        "supply": round(sum(unit.supply_cost for unit in assigned), 1),
                        "supply_budget": requirement.supply_budget,
                        "candidates": candidate_breakdown(requirement, own_units),
                    },
                )
            )

        suitable = any(requirement.matches_identity(unit) for unit in own_units)
        if suitable:
            self._without_candidates.discard(mission_id)
        elif mission_id not in self._without_candidates:
            self._without_candidates.add(mission_id)
            events.append(
                (
                    "capability_no_suitable_candidates",
                    {
                        "role": capability.name,
                        "candidates": candidate_breakdown(requirement, own_units),
                    },
                )
            )
        return events

    def forget(self, mission_id: str) -> None:
        self._compositions.pop(mission_id, None)
        self._without_candidates.discard(mission_id)


def candidate_breakdown(
    requirement: UnitRequirement, units: tuple[UnitSnapshot, ...]
) -> list[dict[str, Any]]:
    """One line per profiled unit type the bot owns, best fit first."""

    capability = requirement.capability
    if capability is None:
        return []
    by_type: dict[str, list[UnitSnapshot]] = {}
    for unit in units:
        if capabilities_for(unit.unit_type) is not None:
            by_type.setdefault(unit.unit_type.name, []).append(unit)

    lines: list[dict[str, Any]] = []
    for name, members in by_type.items():
        sample = members[0]
        profile = capabilities_for(sample.unit_type)
        assert profile is not None
        suitability = score_unit_for_requirement(sample.unit_type, capability)
        lines.append(
            {
                "unit_type": name,
                "count": len(members),
                "utility": round(requirement.utility_for(sample), 3),
                **suitability.log_fields(),
                "capabilities": {
                    dimension.value: profile.value_of(dimension)
                    for dimension in Capability
                },
            }
        )
    return sorted(lines, key=lambda line: (-line["utility"], line["unit_type"]))

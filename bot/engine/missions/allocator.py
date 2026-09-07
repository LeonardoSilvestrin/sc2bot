from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions.models import UnitRequirement
from bot.world.observation.models import UnitSnapshot


@dataclass(frozen=True, slots=True)
class UnitTransfer:
    unit_tag: int
    from_mission_id: str
    to_mission_id: str


@dataclass(frozen=True, slots=True)
class AllocationResult:
    assigned_tags: tuple[int, ...]
    requirements_satisfied: bool
    transfers: tuple[UnitTransfer, ...] = ()


@dataclass(frozen=True, slots=True)
class UnitLease:
    mission_id: str
    priority: int
    protected_until: float


class UnitAllocator:
    """Exclusive unit leases with deterministic, hysteretic preemption."""

    def __init__(self, *, preemption_margin: int = 10) -> None:
        if preemption_margin < 1:
            raise ValueError("preemption_margin must be positive")
        self.preemption_margin = preemption_margin
        self._units: dict[int, UnitSnapshot] = {}
        self._leases: dict[int, UnitLease] = {}

    def sync(self, units: tuple[UnitSnapshot, ...]) -> None:
        self._units = {unit.tag: unit for unit in units}
        self._leases = {
            tag: lease for tag, lease in self._leases.items() if tag in self._units
        }

    def owner_of(self, unit_tag: int) -> str | None:
        lease = self._leases.get(unit_tag)
        return None if lease is None else lease.mission_id

    def unit_type(self, unit_tag: int) -> UnitTypeId | None:
        unit = self._units.get(unit_tag)
        return None if unit is None else unit.unit_type

    def assigned_tags(self, mission_id: str) -> tuple[int, ...]:
        return tuple(
            sorted(
                tag
                for tag, lease in self._leases.items()
                if lease.mission_id == mission_id and tag in self._units
            )
        )

    def assigned_units(self, mission_id: str) -> tuple[UnitSnapshot, ...]:
        return tuple(self._units[tag] for tag in self.assigned_tags(mission_id))

    @staticmethod
    def _score(unit: UnitSnapshot, objective: Point2 | None) -> tuple[float, int]:
        distance = 0.0 if objective is None else unit.position.distance_to(objective)
        return (float(distance) - unit.health_percentage * 10.0, unit.tag)

    def allocate(
        self,
        *,
        mission_id: str,
        priority: int,
        requirement: UnitRequirement,
        objective: Point2 | None,
        now: float,
        can_preempt: bool,
        commitment_seconds: float,
    ) -> AllocationResult:
        existing = sorted(
            (
                unit
                for unit in self.assigned_units(mission_id)
                if requirement.matches_identity(unit)
            ),
            key=lambda unit: self._score(unit, objective),
        )[: requirement.desired]
        needed = requirement.desired - len(existing)
        free = sorted(
            (
                unit
                for unit in self._units.values()
                if unit.tag not in self._leases and requirement.matches(unit)
            ),
            key=lambda unit: self._score(unit, objective),
        )
        preemptible = sorted(
            (
                unit
                for unit in self._units.values()
                if can_preempt
                and (lease := self._leases.get(unit.tag)) is not None
                and lease.mission_id != mission_id
                and priority >= lease.priority + self.preemption_margin
                and now >= lease.protected_until
                and requirement.matches(unit, check_availability=False)
            ),
            key=lambda unit: self._score(unit, objective),
        )

        if len(existing) + len(free) + len(preemptible) < requirement.minimum:
            return AllocationResult(
                assigned_tags=self.assigned_tags(mission_id),
                requirements_satisfied=False,
            )

        selected = [*existing, *free[:needed]]
        transfers: list[UnitTransfer] = []
        for unit in preemptible[: requirement.desired - len(selected)]:
            previous = self._leases[unit.tag]
            transfers.append(UnitTransfer(unit.tag, previous.mission_id, mission_id))
            selected.append(unit)

        for unit in selected:
            if self.owner_of(unit.tag) != mission_id:
                self._leases[unit.tag] = UnitLease(
                    mission_id=mission_id,
                    priority=priority,
                    protected_until=now + commitment_seconds,
                )

        assigned = self.assigned_tags(mission_id)
        return AllocationResult(
            assigned_tags=assigned,
            requirements_satisfied=len(selected) >= requirement.minimum,
            transfers=tuple(transfers),
        )

    def release_mission(self, mission_id: str) -> tuple[int, ...]:
        tags = self.assigned_tags(mission_id)
        for tag in tags:
            del self._leases[tag]
        return tags

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions.models import UnitRequirement
from bot.world.attention import UnitSnapshot


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
    released_tags: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class UnitLease:
    mission_id: str
    priority: int
    protected_until: float
    # What the current owner says it would cost to take this unit away right
    # now (see `MissionExecutor.preemption_cost`). Added to the preemption
    # margin, so a mission mid-strike is harder to raid than the same mission
    # still flying out. 0.0 -- the default for every executor that does not
    # answer -- keeps arbitration purely priority-based.
    preemption_cost: float = 0.0


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
        preferred_tags: frozenset[int] = frozenset(),
        preemption_cost: float = 0.0,
    ) -> AllocationResult:
        currently_assigned = self.assigned_units(mission_id)
        identity_matched = sorted(
            (unit for unit in currently_assigned if requirement.matches_identity(unit)),
            key=lambda unit: self._score(unit, objective),
        )
        existing = identity_matched[: requirement.desired]
        existing_tags = {unit.tag for unit in existing}
        # A shrunk `desired` (or a unit that no longer matches identity) must
        # give up its excess leases immediately -- not linger until some
        # other mission happens to preempt them (see DispositionPlanner
        # posture transitions, e.g. PRESSURE -> BALANCED).
        released_tags = tuple(
            sorted(
                unit.tag for unit in currently_assigned if unit.tag not in existing_tags
            )
        )
        needed = requirement.desired - len(existing)
        free = sorted(
            (
                unit
                for unit in self._units.values()
                if unit.tag not in self._leases
                and requirement.matches(unit)
                # A unit the requesting behavior assigns no utility is not a
                # candidate at all -- never requested, never preempted for.
                and requirement.utility_for(unit) > 0.0
            ),
            key=lambda unit: (
                0 if unit.tag in preferred_tags else 1,
                -requirement.utility_for(unit),
                self._score(unit, objective),
            ),
        )
        preemptible = sorted(
            (
                unit
                for unit in self._units.values()
                if can_preempt
                and (lease := self._leases.get(unit.tag)) is not None
                and lease.mission_id != mission_id
                and priority
                >= lease.priority + self.preemption_margin + lease.preemption_cost
                and now >= lease.protected_until
                and requirement.matches(unit, check_availability=False)
                and requirement.utility_for(unit) > 0.0
            ),
            key=lambda unit: (
                0 if unit.tag in preferred_tags else 1,
                -requirement.utility_for(unit),
                self._score(unit, objective),
            ),
        )

        if len(existing) + len(free) + len(preemptible) < requirement.minimum:
            return AllocationResult(
                assigned_tags=tuple(sorted(existing_tags)),
                requirements_satisfied=False,
                released_tags=released_tags,
            )

        candidates = sorted(
            (*free, *preemptible),
            key=lambda unit: (
                0 if unit.tag in preferred_tags else 1,
                -requirement.utility_for(unit),
                0 if unit.tag not in self._leases else 1,
                self._score(unit, objective),
            ),
        )
        selected = [*existing, *candidates[:needed]]
        transfers: list[UnitTransfer] = []
        for unit in selected[len(existing) :]:
            previous = self._leases.get(unit.tag)
            if previous is not None:
                transfers.append(
                    UnitTransfer(unit.tag, previous.mission_id, mission_id)
                )

        for unit in selected:
            if self.owner_of(unit.tag) != mission_id:
                self._leases[unit.tag] = UnitLease(
                    mission_id=mission_id,
                    priority=priority,
                    protected_until=now + commitment_seconds,
                    preemption_cost=preemption_cost,
                )
            elif self._leases[unit.tag].preemption_cost != preemption_cost:
                # The owner's own cost changes as it progresses (ASSEMBLE ->
                # STRIKE); refresh it without disturbing the commitment window.
                self._leases[unit.tag] = replace(
                    self._leases[unit.tag], preemption_cost=preemption_cost
                )

        assigned = tuple(sorted(unit.tag for unit in selected))
        return AllocationResult(
            assigned_tags=assigned,
            requirements_satisfied=len(selected) >= requirement.minimum,
            transfers=tuple(transfers),
            released_tags=released_tags,
        )

    def release_mission(self, mission_id: str) -> tuple[int, ...]:
        tags = self.assigned_tags(mission_id)
        for tag in tags:
            del self._leases[tag]
        return tags

    def release_units(self, mission_id: str, tags: Iterable[int]) -> None:
        """Drop specific leases still owned by ``mission_id``.

        Used for leases the mission itself is giving up (e.g. a shrunk
        ``desired``) as opposed to `release_mission`, which tears down every
        lease when the mission ends entirely.
        """

        for tag in tags:
            lease = self._leases.get(tag)
            if lease is not None and lease.mission_id == mission_id:
                del self._leases[tag]

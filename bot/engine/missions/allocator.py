from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions.models import UnitRequirement
from bot.world.attention import UnitSnapshot

# Suitability is a coarse heuristic: utilities closer than this rank as equal,
# so distance decides between a Marine and a Marauder that fit a role almost
# identically instead of the third decimal sending the far one across the map.
UTILITY_RESOLUTION = 0.05

# Only absorbs float noise in budgets such as `10 * 0.2`.
_SUPPLY_EPSILON = 1e-6


@dataclass(frozen=True, slots=True)
class UnitTransfer:
    unit_tag: int
    from_mission_id: str
    to_mission_id: str


@dataclass(frozen=True, slots=True)
class UnitUpgrade:
    """A held unit swapped out for a clearly more suitable one."""

    released_tag: int
    acquired_tag: int
    released_utility: float
    acquired_utility: float


@dataclass(frozen=True, slots=True)
class AllocationResult:
    assigned_tags: tuple[int, ...]
    requirements_satisfied: bool
    transfers: tuple[UnitTransfer, ...] = ()
    # Every lease the mission gives up, upgrades' swapped-out units included.
    released_tags: tuple[int, ...] = ()
    upgrades: tuple[UnitUpgrade, ...] = ()


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


def _supply(units: Iterable[UnitSnapshot]) -> float:
    return sum(unit.supply_cost for unit in units)


class UnitAllocator:
    """Exclusive unit leases with deterministic, hysteretic preemption.

    Candidates are every unit the bot owns. Hard constraints
    (``UnitRequirement.matches``, zero utility) decide who is one, utility
    decides which is taken first, and the requirement's size -- ``desired``
    units, and ``supply_budget`` when set -- decides how many. The allocator
    knows no unit list beyond what an identity requirement names, and nothing
    about what is being produced.

    A held unit is never displaced for a marginally better one: only a
    capability-based mission that is already full may swap its least
    suitable unit, and only for a candidate it could preempt anyway whose
    utility is higher by at least ``upgrade_margin``.
    """

    def __init__(
        self, *, preemption_margin: int = 10, upgrade_margin: float = 0.15
    ) -> None:
        if preemption_margin < 1:
            raise ValueError("preemption_margin must be positive")
        if upgrade_margin <= 0.0:
            raise ValueError("upgrade_margin must be positive")
        self.preemption_margin = preemption_margin
        self.upgrade_margin = upgrade_margin
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

    def unit_supply(self, unit_tag: int) -> float:
        unit = self._units.get(unit_tag)
        return 0.0 if unit is None else unit.supply_cost

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

    @staticmethod
    def _ranked_utility(requirement: UnitRequirement, unit: UnitSnapshot) -> int:
        return round(requirement.utility_for(unit) / UTILITY_RESOLUTION)

    @staticmethod
    def _has_room(requirement: UnitRequirement, *, count: int, supply: float) -> bool:
        """Whether the requirement wants another unit on top of these.

        ``desired`` caps the count. A ``supply_budget`` admits another unit
        while the supply already taken is below it, so the last unit may
        overshoot by less than its own supply rather than leaving the budget
        unfilled for want of a small enough unit.
        """

        if count >= requirement.desired:
            return False
        budget = requirement.supply_budget
        return budget is None or supply < budget - _SUPPLY_EPSILON

    @classmethod
    def _fill(
        cls,
        requirement: UnitRequirement,
        ranked: Iterable[UnitSnapshot],
        *,
        held: tuple[UnitSnapshot, ...] | list[UnitSnapshot] = (),
    ) -> list[UnitSnapshot]:
        """Take ``ranked`` units in order while the requirement has room.

        One at a time on purpose: today each unit's utility is its
        standalone suitability, fixed by the ranking; this loop is where its
        worth *given the units already taken* would be evaluated instead.
        """

        count, supply = len(held), _supply(held)
        taken: list[UnitSnapshot] = []
        for unit in ranked:
            if not cls._has_room(requirement, count=count, supply=supply):
                break
            taken.append(unit)
            count += 1
            supply += unit.supply_cost
        return taken

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
        capability_based = requirement.capability is not None
        currently_assigned = self.assigned_units(mission_id)
        identity_matched = sorted(
            (unit for unit in currently_assigned if requirement.matches_identity(unit)),
            key=lambda unit: (
                # A shrinking capability mission keeps its best-suited units.
                -self._ranked_utility(requirement, unit) if capability_based else 0,
                self._score(unit, objective),
            ),
        )
        existing = self._fill(requirement, identity_matched)
        existing_tags = {unit.tag for unit in existing}
        # A shrunk size (or a unit that no longer matches identity) must give
        # up its excess leases immediately -- not linger until some other
        # mission happens to preempt them (see DispositionPlanner posture
        # transitions, e.g. PRESSURE -> BALANCED).
        released = [
            unit.tag for unit in currently_assigned if unit.tag not in existing_tags
        ]

        def candidate_key(unit: UnitSnapshot) -> tuple:
            return (
                0 if unit.tag in preferred_tags else 1,
                -self._ranked_utility(requirement, unit),
                0 if unit.tag not in self._leases else 1,
                self._score(unit, objective),
            )

        free = [
            unit
            for unit in self._units.values()
            if unit.tag not in self._leases
            and requirement.matches(unit)
            # A unit the requesting behavior assigns no utility is not a
            # candidate at all -- never requested, never preempted for.
            and requirement.utility_for(unit) > 0.0
        ]
        preemptible = [
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
        ]

        if len(existing) + len(free) + len(preemptible) < requirement.minimum:
            return AllocationResult(
                assigned_tags=tuple(sorted(existing_tags)),
                requirements_satisfied=False,
                released_tags=tuple(sorted(released)),
            )

        candidates = sorted((*free, *preemptible), key=candidate_key)
        acquired = self._fill(requirement, candidates, held=existing)
        upgrades: tuple[UnitUpgrade, ...] = ()
        if capability_based and not self._has_room(
            requirement, count=len(existing), supply=_supply(existing)
        ):
            existing, swaps = self._upgrades(
                requirement,
                held=existing,
                # Only units it could preempt: their donor ranks lower, so it
                # allocates later this same tick and can take back the unit
                # this swap releases instead of leaving it ownerless.
                candidates=sorted(preemptible, key=candidate_key),
            )
            upgrades = tuple(swaps)
            released.extend(upgrade.released_tag for upgrade in upgrades)
            acquired = [self._units[upgrade.acquired_tag] for upgrade in upgrades]

        selected = [*existing, *acquired]
        transfers: list[UnitTransfer] = []
        for unit in acquired:
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
            released_tags=tuple(sorted(released)),
            upgrades=upgrades,
        )

    def _upgrades(
        self,
        requirement: UnitRequirement,
        *,
        held: list[UnitSnapshot],
        candidates: list[UnitSnapshot],
    ) -> tuple[list[UnitSnapshot], list[UnitUpgrade]]:
        """Swap the least suitable held units for clearly better candidates.

        Each swap raises the mission's utility by at least ``upgrade_margin``,
        so a sequence of them always ends, and small score differences --
        Marine against Marauder -- never move a unit at all. A swap may raise
        the supply held past a budget; the next allocation trims the surplus
        from the least suitable end.
        """

        kept = sorted(
            held,
            key=lambda unit: (requirement.utility_for(unit), -unit.tag),
            reverse=True,
        )
        incoming: list[UnitSnapshot] = []
        swaps: list[UnitUpgrade] = []
        for candidate in candidates:
            if not kept:
                break
            worst = kept[-1]
            if not self._has_room(
                requirement,
                count=len(kept) - 1 + len(incoming),
                supply=_supply(kept) - worst.supply_cost + _supply(incoming),
            ):
                # Over budget even without it: surplus to trim, not to swap.
                break
            gain = requirement.utility_for(candidate) - requirement.utility_for(worst)
            if gain < self.upgrade_margin:
                continue
            kept.pop()
            incoming.append(candidate)
            swaps.append(
                UnitUpgrade(
                    released_tag=worst.tag,
                    acquired_tag=candidate.tag,
                    released_utility=requirement.utility_for(worst),
                    acquired_utility=requirement.utility_for(candidate),
                )
            )
        return kept, swaps

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

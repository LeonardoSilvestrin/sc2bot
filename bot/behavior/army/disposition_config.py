from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId

from .combat_posture import CombatPosture

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
        UnitTypeId.BANSHEE,
    }
)


@dataclass(frozen=True, slots=True)
class PostureDesired:
    """How many units each standing slot wants under one CombatPosture.

    A slot proposes nothing when its count is 0 (e.g. no ``forward`` slot
    outside PRESSURE/BALANCED). ``main``/``natural``/``third`` are only
    proposed if that base is actually currently held -- see
    ``DispositionPlanner._ranked_bases``.
    """

    main: int
    natural: int
    third: int
    forward: int = 0

    def __post_init__(self) -> None:
        for name in ("main", "natural", "third", "forward"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")


def default_posture_desired() -> Mapping[CombatPosture, PostureDesired]:
    return {
        # third > natural > main: prioritize the more exposed expansions.
        CombatPosture.TURTLE: PostureDesired(main=2, natural=4, third=6),
        # A little of everything, plus a small central/staging presence.
        CombatPosture.BALANCED: PostureDesired(main=2, natural=3, third=3, forward=2),
        # Minimal defensive garrisons; most of the force sits forward.
        CombatPosture.PRESSURE: PostureDesired(main=1, natural=1, third=1, forward=6),
    }


@dataclass(frozen=True, slots=True)
class DispositionPlannerConfig:
    """Thresholds for the standing army-disposition planner.

    Priorities are fixed per structural slot (not per posture): how exposed
    ``third`` is relative to ``main`` is a geography fact, not a policy
    choice, so it stays constant across postures -- only how many units
    each slot *wants* (``desired_by_posture``) changes with ``CombatPosture``.

    Every priority here is kept comfortably below ``MAP_CONTROL`` (40) and
    ``HARASS`` (60+) with the allocator's default preemption margin (10), so
    a standing mission is always freely preemptible by either -- see
    ``UnitAllocator.allocate`` and Invariant 2 in the disposition pilot.
    ``reserve_priority`` stays below every slot for the same reason.
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

    main_priority: int = 12
    natural_priority: int = 18
    third_priority: int = 30
    forward_priority: int = 25
    reserve_priority: int = 5

    desired_by_posture: Mapping[CombatPosture, PostureDesired] = field(
        default_factory=default_posture_desired
    )

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
        priorities = (
            self.main_priority,
            self.natural_priority,
            self.third_priority,
            self.forward_priority,
            self.reserve_priority,
        )
        if any(not 0 <= priority <= 100 for priority in priorities):
            raise ValueError("priorities must be between 0 and 100")
        if set(self.desired_by_posture) != set(CombatPosture):
            raise ValueError("desired_by_posture must cover every CombatPosture")

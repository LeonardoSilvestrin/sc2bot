from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.world.attention import UnitSnapshot


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

    @classmethod
    def combat(
        cls,
        *,
        unit_types: frozenset[UnitTypeId],
        desired: int,
        minimum: int,
        minimum_health: float = 0.0,
    ) -> UnitRequirement:
        """A requirement for a mobile combat/utility mission.

        Every such mission planner needs the same two exclusions: never pull
        a worker that is mid-return-cargo, and never pull one that is
        mid-construction. Both would otherwise abandon useful work already
        in flight.
        """

        return cls(
            unit_types=unit_types,
            desired=desired,
            minimum=minimum,
            minimum_health=minimum_health,
            exclude_resource_carriers=True,
            exclude_constructors=True,
        )


class MissionKind(Enum):
    SCOUT = auto()
    HARASS = auto()
    AIR_HARASS = auto()
    DEFENSE = auto()
    MAP_CONTROL = auto()
    POSITION = auto()


class MissionMode(Enum):
    """Whether a mission is a one-shot job or a permanent responsibility.

    ``FINITE`` is the existing behavior: a proposal is admitted once, runs to
    completion/failure/cancellation, and a second proposal for the same
    ``deduplication_key`` while it is live is rejected as a duplicate.

    ``STANDING`` describes an ongoing responsibility (see
    ``bot.behavior.army.DispositionPlanner``) that a planner re-proposes on
    every cadence tick. A live ``STANDING`` mission is never rejected as a
    duplicate -- its ``Mission.proposal`` is replaced in place so the same
    mission_id/lease history continues, only the requirement/priority/target
    change. See ``MissionController._update_standing``.
    """

    FINITE = auto()
    STANDING = auto()


class MissionStatus(Enum):
    PROPOSED = auto()
    QUEUED = auto()
    ACTIVE = auto()
    BLOCKED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


@dataclass(frozen=True, slots=True)
class MissionProposal:
    """A planner's argument for work; it is not yet a commitment."""

    proposal_id: str
    deduplication_key: str
    planner: str
    kind: MissionKind
    priority: int
    target_key: str
    target: Point2
    reason: str
    requirement: UnitRequirement
    created_at: float
    evidence_last_observed_at: float | None = None
    evidence_age: float | None = None
    evidence_stale_after: float | None = None
    timeout_seconds: float = 70.0
    cooldown_seconds: float = 65.0
    can_preempt: bool = False
    commitment_seconds: float = 5.0
    mode: MissionMode = MissionMode.FINITE

    def __post_init__(self) -> None:
        text_fields = (
            self.proposal_id,
            self.deduplication_key,
            self.planner,
            self.target_key,
            self.reason,
        )
        if any(not value.strip() for value in text_fields):
            raise ValueError("proposal identifiers and reason must not be empty")
        if not 0 <= self.priority <= 100:
            raise ValueError("priority must be between 0 and 100")
        if self.timeout_seconds <= 0.0 or self.cooldown_seconds < 0.0:
            raise ValueError("invalid timeout or cooldown")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")


@dataclass(slots=True)
class Mission:
    """A proposal admitted as a real bot commitment."""

    mission_id: str
    proposal: MissionProposal
    admitted_at: float
    status: MissionStatus = MissionStatus.PROPOSED
    assigned_unit_tags: tuple[int, ...] = ()
    started_at: float | None = None
    finished_at: float | None = None
    last_reason: str = "proposal_received"


@dataclass(frozen=True, slots=True)
class MissionSnapshot:
    mission_id: str
    proposal_id: str
    deduplication_key: str
    planner: str
    kind: MissionKind
    priority: int
    status: MissionStatus
    assigned_unit_tags: tuple[int, ...]
    reason: str
    admitted_at: float
    started_at: float | None
    finished_at: float | None

    @classmethod
    def from_mission(cls, mission: Mission) -> MissionSnapshot:
        return cls(
            mission_id=mission.mission_id,
            proposal_id=mission.proposal.proposal_id,
            deduplication_key=mission.proposal.deduplication_key,
            planner=mission.proposal.planner,
            kind=mission.proposal.kind,
            priority=mission.proposal.priority,
            status=mission.status,
            assigned_unit_tags=mission.assigned_unit_tags,
            reason=mission.last_reason,
            admitted_at=mission.admitted_at,
            started_at=mission.started_at,
            finished_at=mission.finished_at,
        )

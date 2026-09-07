from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from sc2.position import Point2

from bot.contracts.allocation import UnitRequirement


class MissionKind(Enum):
    SCOUT = auto()
    HARASS = auto()
    DEFENSE = auto()


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

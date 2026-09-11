from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum, auto
from typing import Protocol

from sc2.position import Point2


class VisionUrgency(IntEnum):
    LOW = 25
    NORMAL = 50
    HIGH = 75
    CRITICAL = 100


class VisionRequestStatus(Enum):
    SATISFIED = auto()
    PENDING = auto()
    UNAVAILABLE = auto()


@dataclass(frozen=True, slots=True)
class VisionRequestResult:
    request_id: str
    status: VisionRequestStatus
    reason: str


class VisionRequester(Protocol):
    """The only active-vision surface a behavior needs to know."""

    def request(
        self,
        *,
        position: Point2,
        urgency: VisionUrgency,
        reason: str,
        requester: str,
        ttl: float,
    ) -> VisionRequestResult:
        ...

    def result(self, request_id: str) -> VisionRequestResult | None:
        ...


@dataclass(frozen=True, slots=True)
class VisionServiceConfig:
    spatial_deduplication_radius: float = 10.0
    scan_cooldown_radius: float = 13.0
    scan_cooldown: float = 15.0
    deduplication_log_cooldown: float = 15.0
    max_provider_attempts_per_frame: int = 1

    def __post_init__(self) -> None:
        if self.spatial_deduplication_radius <= 0.0:
            raise ValueError("spatial_deduplication_radius must be positive")
        if self.scan_cooldown_radius <= 0.0 or self.scan_cooldown < 0.0:
            raise ValueError("scan cooldown radius must be positive")
        if self.deduplication_log_cooldown < 0.0:
            raise ValueError("deduplication_log_cooldown must not be negative")
        if self.max_provider_attempts_per_frame < 1:
            raise ValueError("max_provider_attempts_per_frame must be at least 1")


@dataclass(slots=True)
class VisionRequest:
    request_id: str
    position: Point2
    urgency: VisionUrgency
    requester: str
    reason: str
    created_at: float
    expires_at: float
    status: VisionRequestStatus = VisionRequestStatus.PENDING
    status_reason: str = "awaiting_resolution"
    last_dispatch_at: float | None = None
    last_deduplication_log_at: float | None = None
    last_deferred_log_at: float | None = None

    def snapshot(self) -> VisionRequestResult:
        return VisionRequestResult(
            request_id=self.request_id,
            status=self.status,
            reason=self.status_reason,
        )


@dataclass(frozen=True, slots=True)
class ProviderDispatchResult:
    accepted: bool
    reason: str
    provider: str
    orbital_tag: int | None = None
    orbital_energy: float | None = None

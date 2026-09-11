from __future__ import annotations

from dataclasses import dataclass, field

from sc2.position import Point2

from bot.ports.logging import BotLogger
from bot.ports.vision_commands import VisionCommands
from bot.world.attention import AttentionSnapshot

from .model import (
    VisionRequest,
    VisionRequester,
    VisionRequestResult,
    VisionRequestStatus,
    VisionServiceConfig,
    VisionUrgency,
)
from .scan_provider import ScanProvider

COMPONENT = "engine.services.vision"


@dataclass(slots=True)
class VisionService(VisionRequester):
    """Persist, deduplicate and arbitrate short-lived active-vision needs."""

    provider: ScanProvider = field(default_factory=ScanProvider)
    config: VisionServiceConfig = field(default_factory=VisionServiceConfig)
    logger: BotLogger | None = None
    _now: float | None = field(default=None, init=False, repr=False)
    _commands: VisionCommands | None = field(default=None, init=False, repr=False)
    _requests: dict[str, VisionRequest] = field(
        default_factory=dict, init=False, repr=False
    )
    _recent_dispatches: list[tuple[Point2, float]] = field(
        default_factory=list, init=False, repr=False
    )
    _sequence: int = field(default=0, init=False, repr=False)

    def begin_frame(
        self, attention: AttentionSnapshot, commands: VisionCommands
    ) -> None:
        world = attention.world
        self._now = world.time
        self._commands = commands
        self.provider.begin_frame(world, commands)
        self._requests = {
            key: request
            for key, request in self._requests.items()
            if request.expires_at >= world.time
        }
        self._recent_dispatches = [
            item
            for item in self._recent_dispatches
            if world.time - item[1] < self.config.scan_cooldown
        ]
        for request in self._requests.values():
            if commands.has_vision(request.position):
                self._set_satisfied(request)
            elif request.status is VisionRequestStatus.SATISFIED:
                request.status = VisionRequestStatus.PENDING
                request.status_reason = "vision_lost_while_request_active"

    def request(
        self,
        *,
        position: Point2,
        urgency: VisionUrgency,
        reason: str,
        requester: str,
        ttl: float,
    ) -> VisionRequestResult:
        now, commands = self._frame()
        if not requester.strip() or not reason.strip():
            raise ValueError("requester and reason must not be empty")
        if ttl <= 0.0:
            raise ValueError("ttl must be positive")

        existing = self._matching_request(position)
        if existing is not None:
            existing.expires_at = max(existing.expires_at, now + ttl)
            existing.urgency = max(existing.urgency, urgency)
            if commands.has_vision(position):
                self._set_satisfied(existing)
            self._log_deduplicated(existing, requester=requester, reason=reason)
            return existing.snapshot()

        self._sequence += 1
        request = VisionRequest(
            request_id=f"vision-{self._sequence:04d}",
            position=position,
            urgency=urgency,
            requester=requester,
            reason=reason,
            created_at=now,
            expires_at=now + ttl,
        )
        self._requests[request.request_id] = request
        self._event(
            "vision.request_created",
            request,
            ttl=ttl,
        )
        if commands.has_vision(position):
            self._set_satisfied(request)
        return request.snapshot()

    def result(self, request_id: str) -> VisionRequestResult | None:
        request = self._requests.get(request_id)
        return None if request is None else request.snapshot()

    def resolve(self) -> tuple[VisionRequestResult, ...]:
        now, commands = self._frame()
        for request in self._requests.values():
            if commands.has_vision(request.position):
                self._set_satisfied(request)

        candidates = sorted(
            (
                request
                for request in self._requests.values()
                if request.status is not VisionRequestStatus.SATISFIED
                and not self._covered_by_recent_dispatch(request.position, now)
            ),
            key=lambda request: (-int(request.urgency), request.created_at),
        )
        attempts = 0
        for request in candidates:
            if attempts >= self.config.max_provider_attempts_per_frame:
                break
            if self._should_log_selection(request, now):
                self._event("vision.request_selected", request)
            attempts += 1
            outcome = self.provider.dispatch(request)
            if outcome.accepted:
                request.status = VisionRequestStatus.PENDING
                request.status_reason = outcome.reason
                request.last_dispatch_at = now
                self._recent_dispatches.append((request.position, now))
                continue
            request.status = VisionRequestStatus.UNAVAILABLE
            request.status_reason = outcome.reason
            self._log_deferred(request)
        return tuple(request.snapshot() for request in self._requests.values())

    def _should_log_selection(self, request: VisionRequest, now: float) -> bool:
        last = request.last_deferred_log_at
        return (
            request.status is not VisionRequestStatus.UNAVAILABLE
            or last is None
            or now - last >= self.config.deduplication_log_cooldown
        )

    def _frame(self) -> tuple[float, VisionCommands]:
        if self._now is None or self._commands is None:
            raise RuntimeError("VisionService.begin_frame must run first")
        return self._now, self._commands

    def _matching_request(self, position: Point2) -> VisionRequest | None:
        return next(
            (
                request
                for request in self._requests.values()
                if request.position.distance_to(position)
                <= self.config.spatial_deduplication_radius
            ),
            None,
        )

    def _covered_by_recent_dispatch(self, position: Point2, now: float) -> bool:
        return any(
            now - dispatched_at < self.config.scan_cooldown
            and dispatched_position.distance_to(position)
            <= self.config.scan_cooldown_radius
            for dispatched_position, dispatched_at in self._recent_dispatches
        )

    def _set_satisfied(self, request: VisionRequest) -> None:
        if request.status is VisionRequestStatus.SATISFIED:
            return
        request.status = VisionRequestStatus.SATISFIED
        request.status_reason = "position_visible"
        self._event("vision.request_satisfied", request)

    def _log_deduplicated(
        self, request: VisionRequest, *, requester: str, reason: str
    ) -> None:
        now, _ = self._frame()
        last = request.last_deduplication_log_at
        if last is not None and now - last < self.config.deduplication_log_cooldown:
            return
        request.last_deduplication_log_at = now
        self._event(
            "vision.request_deduplicated",
            request,
            duplicate_requester=requester,
            duplicate_reason=reason,
        )

    def _log_deferred(self, request: VisionRequest) -> None:
        now, _ = self._frame()
        last = request.last_deferred_log_at
        if last is not None and now - last < self.config.deduplication_log_cooldown:
            return
        request.last_deferred_log_at = now
        self._event("vision.request_deferred", request)

    def _event(self, name: str, request: VisionRequest, **data: object) -> None:
        if self.logger is None:
            return
        now, _ = self._frame()
        self.logger.event(
            name,
            component=COMPONENT,
            game_time=now,
            data={
                "request_id": request.request_id,
                "requester": request.requester,
                "reason": request.reason,
                "position": [request.position.x, request.position.y],
                "urgency": request.urgency.name,
                "status": request.status.name,
                "status_reason": request.status_reason,
                **data,
            },
        )

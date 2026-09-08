from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from bot.engine.missions.allocator import AllocationResult, UnitAllocator
from bot.engine.missions.board import MissionBoard
from bot.engine.missions.execution import (
    MissionContext,
    MissionExecutor,
    MissionExecutorFactory,
    MissionOutcome,
)
from bot.engine.missions.models import (
    Mission,
    MissionKind,
    MissionProposal,
    MissionSnapshot,
    MissionStatus,
)
from bot.ports.logging import BotLogger
from bot.ports.mission_commands import MissionCommands
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot


class MissionController:
    """Admits proposals, owns mission lifecycle, and arbitrates unit leases."""

    def __init__(
        self,
        *,
        logger: BotLogger,
        allocator: UnitAllocator | None = None,
        board: MissionBoard | None = None,
        executor_factories: Mapping[MissionKind, MissionExecutorFactory],
    ) -> None:
        self.logger = logger
        self.allocator = allocator or UnitAllocator()
        self.board = board or MissionBoard()
        self._executor_factories = executor_factories
        self._executors: dict[str, MissionExecutor] = {}
        self._processed_proposals: set[str] = set()
        self._cooldown_until: dict[str, float] = {}
        self._mission_sequence = 0

    def snapshots(self) -> tuple[MissionSnapshot, ...]:
        return self.board.snapshots()

    async def tick(
        self,
        *,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
        proposals: tuple[MissionProposal, ...],
        commands: MissionCommands,
    ) -> None:
        now = attention.world.time
        self.allocator.sync(attention.world.own_units)
        # Check losses before allocation can silently replace the entire team.
        for mission in self.board.live():
            if (
                mission.started_at is not None
                and mission.assigned_unit_tags
                and not self.allocator.assigned_tags(mission.mission_id)
            ):
                self._finish(
                    mission,
                    MissionStatus.FAILED,
                    "all_assigned_units_lost",
                    now,
                    commands,
                )
        for proposal in proposals:
            self._consider(proposal, now)

        missions = sorted(
            self.board.live(),
            key=lambda item: (-item.proposal.priority, item.admitted_at),
        )
        for mission in missions:
            if mission.status.terminal:
                continue
            cancel_reason = self._cancellation_reason(mission, now, awareness)
            if cancel_reason is not None:
                self._finish(
                    mission, MissionStatus.CANCELLED, cancel_reason, now, commands
                )
                continue

            allocation = self.allocator.allocate(
                mission_id=mission.mission_id,
                priority=mission.proposal.priority,
                requirement=mission.proposal.requirement,
                objective=mission.proposal.target,
                now=now,
                can_preempt=mission.proposal.can_preempt,
                commitment_seconds=mission.proposal.commitment_seconds,
            )
            self._apply_allocation(mission, allocation, now, commands)

            if not allocation.requirements_satisfied:
                if mission.started_at is not None and not allocation.assigned_tags:
                    self._finish(
                        mission,
                        MissionStatus.FAILED,
                        "all_assigned_units_lost",
                        now,
                        commands,
                    )
                else:
                    self._block(mission, "unit_requirements_not_satisfied", now)
                continue

            await self._advance_executor(mission, now, attention, awareness, commands)

    def _cancellation_reason(
        self, mission: Mission, now: float, awareness: AwarenessSnapshot
    ) -> str | None:
        location = awareness.enemy.location(mission.proposal.target_key)
        if (
            mission.started_at is None
            and location is not None
            and location.last_observed_at is not None
            and location.last_observed_at > mission.admitted_at
        ):
            return "objective_satisfied_before_mission_started"
        if now - mission.admitted_at >= mission.proposal.timeout_seconds:
            return "mission_timeout"
        return None

    def _apply_allocation(
        self,
        mission: Mission,
        allocation: AllocationResult,
        now: float,
        commands: MissionCommands,
    ) -> None:
        for transfer in allocation.transfers:
            previous = self.board.get(transfer.from_mission_id)
            # Ownership has moved; reset the old role using the authorized owner.
            commands.release(mission_id=mission.mission_id, unit_tag=transfer.unit_tag)
            self._emit(
                "units_reassigned",
                now,
                "higher_priority_after_commitment_window",
                mission=mission,
                unit_tags=[transfer.unit_tag],
                unit_types=self._unit_type_names([transfer.unit_tag]),
                from_mission_id=transfer.from_mission_id,
                from_proposal_id=(
                    previous.proposal.proposal_id if previous is not None else None
                ),
                from_priority=(
                    previous.proposal.priority if previous is not None else None
                ),
            )

        for previous_id in dict.fromkeys(
            transfer.from_mission_id for transfer in allocation.transfers
        ):
            previous = self.board.get(previous_id)
            if previous is not None:
                previous.assigned_unit_tags = self.allocator.assigned_tags(previous_id)
                if not previous.assigned_unit_tags:
                    self._finish(
                        previous,
                        MissionStatus.FAILED,
                        "all_assigned_units_preempted",
                        now,
                        commands,
                    )

        if mission.assigned_unit_tags != allocation.assigned_tags:
            previous_tags = mission.assigned_unit_tags
            mission.assigned_unit_tags = allocation.assigned_tags
            self._emit(
                "units_assigned",
                now,
                "allocator_assignment_changed",
                mission=mission,
                previous_unit_tags=list(previous_tags),
                unit_tags=list(allocation.assigned_tags),
                unit_types=self._unit_type_names(allocation.assigned_tags),
            )

    async def _advance_executor(
        self,
        mission: Mission,
        now: float,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
        commands: MissionCommands,
    ) -> None:
        if mission.started_at is None:
            try:
                executor = self._executor_factories[mission.proposal.kind](mission, now)
            except Exception as error:
                self._finish(
                    mission,
                    MissionStatus.FAILED,
                    f"executor_error:{type(error).__name__}:{error}",
                    now,
                    commands,
                )
                return
            mission.started_at = now
            self._executors[mission.mission_id] = executor
            mission.status = MissionStatus.ACTIVE
            mission.last_reason = "unit_requirements_satisfied"
            self._emit("mission_started", now, mission.last_reason, mission=mission)
        else:
            mission.status = MissionStatus.ACTIVE

        try:
            result = await self._executors[mission.mission_id].step(
                MissionContext(
                    attention=attention,
                    awareness=awareness,
                    assigned_units=self.allocator.assigned_units(mission.mission_id),
                    commands=commands,
                )
            )
        except Exception as error:
            self._finish(
                mission,
                MissionStatus.FAILED,
                f"executor_error:{type(error).__name__}:{error}",
                now,
                commands,
            )
            return

        mission.last_reason = result.reason
        if result.outcome is MissionOutcome.COMPLETED:
            self._finish(
                mission, MissionStatus.COMPLETED, result.reason, now, commands
            )
        elif result.outcome is MissionOutcome.FAILED:
            self._finish(
                mission, MissionStatus.FAILED, result.reason, now, commands
            )

    def _consider(self, proposal: MissionProposal, now: float) -> None:
        if proposal.proposal_id in self._processed_proposals:
            return
        self._processed_proposals.add(proposal.proposal_id)
        self._emit("proposal_created", now, proposal.reason, proposal=proposal)

        live = self.board.live_for_key(proposal.deduplication_key)
        if live is not None:
            self._emit(
                "proposal_rejected",
                now,
                "matching_mission_already_live",
                proposal=proposal,
                conflicting_mission_id=live.mission_id,
            )
            return
        if now < self._cooldown_until.get(proposal.deduplication_key, -1.0):
            self._emit(
                "proposal_rejected",
                now,
                "mission_cooldown_active",
                proposal=proposal,
            )
            return
        if proposal.kind not in self._executor_factories:
            self._emit(
                "proposal_rejected",
                now,
                "unsupported_mission_kind",
                proposal=proposal,
            )
            return

        self._mission_sequence += 1
        mission = Mission(
            mission_id=f"mission-{self._mission_sequence:04d}",
            proposal=proposal,
            admitted_at=now,
        )
        self.board.add(mission)
        self._emit(
            "proposal_admitted",
            now,
            "no_conflicting_live_mission",
            mission=mission,
        )
        mission.status = MissionStatus.QUEUED
        mission.last_reason = "waiting_for_unit_allocation"
        self._emit("mission_queued", now, mission.last_reason, mission=mission)

    def _unit_type_names(self, tags: Iterable[int]) -> list[str | None]:
        return [
            unit_type.name if (unit_type := self.allocator.unit_type(tag)) else None
            for tag in tags
        ]

    def _block(self, mission: Mission, reason: str, now: float) -> None:
        if mission.status is MissionStatus.BLOCKED and mission.last_reason == reason:
            return
        mission.status = MissionStatus.BLOCKED
        mission.last_reason = reason
        self._emit("mission_blocked", now, reason, mission=mission)

    def _finish(
        self,
        mission: Mission,
        status: MissionStatus,
        reason: str,
        now: float,
        commands: MissionCommands,
    ) -> None:
        tags = self.allocator.assigned_tags(mission.mission_id)
        unit_types = self._unit_type_names(tags)
        for tag in tags:
            commands.release(mission_id=mission.mission_id, unit_tag=tag)
        released = self.allocator.release_mission(mission.mission_id)
        if released:
            self._emit(
                "units_released",
                now,
                reason,
                mission=mission,
                unit_tags=list(released),
                unit_types=unit_types,
            )

        mission.assigned_unit_tags = ()
        mission.status = status
        mission.finished_at = now
        mission.last_reason = reason
        self._executors.pop(mission.mission_id, None)
        self._cooldown_until[mission.proposal.deduplication_key] = (
            now + mission.proposal.cooldown_seconds
        )
        event = {
            MissionStatus.COMPLETED: "mission_completed",
            MissionStatus.FAILED: "mission_failed",
            MissionStatus.CANCELLED: "mission_cancelled",
        }[status]
        self._emit(event, now, reason, mission=mission)

    def _emit(
        self,
        event: str,
        now: float,
        reason: str,
        *,
        proposal: MissionProposal | None = None,
        mission: Mission | None = None,
        **extra: Any,
    ) -> None:
        proposal = mission.proposal if mission is not None else proposal
        data: dict[str, Any] = {"reason": reason}
        if proposal is not None:
            data.update(
                proposal_id=proposal.proposal_id,
                deduplication_key=proposal.deduplication_key,
                planner_id=proposal.planner,
                mission_kind=proposal.kind.name,
                priority=proposal.priority,
                target_key=proposal.target_key,
                target=[float(proposal.target.x), float(proposal.target.y)],
                proposal_reason=proposal.reason,
                last_observed_at=proposal.evidence_last_observed_at,
                observation_age=proposal.evidence_age,
                stale_after=proposal.evidence_stale_after,
            )
        if mission is not None:
            data.update(
                mission_id=mission.mission_id,
                status=mission.status.name,
                unit_tags=list(mission.assigned_unit_tags),
            )
        data.update(extra)
        self.logger.event(
            event,
            component="engine.missions.controller",
            game_time=now,
            data=data,
        )

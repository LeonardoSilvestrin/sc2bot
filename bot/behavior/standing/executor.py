"""EXECUTE: keep the core army sitting on its anchor.

A unit already within ``arrival_radius`` of the anchor is left alone -- it
may sit physically idle, which is the correct state for a standing
responsibility. Only units that have drifted out of tolerance (freshly
assigned, pushed off by combat, ...) get a movement command this step.

Never fails and never completes on its own: a standing mission's lifecycle
is driven by proposals and allocation (see
``MissionController._update_standing``), not by executor outcomes. With zero
assigned units -- fully preempted by defense or a raid -- it simply does
nothing that tick, and picks the units back up when they are released.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sc2.position import Point2

from bot.behavior.contracts import BehaviorLog
from bot.engine.missions.execution import (
    MissionContext,
    MissionExecutor,
    MissionOutcome,
    MissionResult,
)
from bot.engine.missions.models import Mission
from bot.ports.logging import BotLogger

COMPONENT = "behavior.standing"


@dataclass(slots=True)
class StandingExecutor(MissionExecutor):
    """Gathers the assigned core army onto the planned anchor."""

    mission_id: str
    target_key: str
    target: Point2
    started_at: float
    arrival_radius: float = 4.0
    logger: BotLogger | None = None
    _log: BehaviorLog = field(init=False, repr=False)
    _last_anchor: Point2 | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._log = BehaviorLog(component=COMPONENT, logger=self.logger)

    def refresh(self, mission: Mission) -> None:
        self.target_key = mission.proposal.target_key
        self.target = mission.proposal.target

    async def step(self, context: MissionContext) -> MissionResult:
        units = context.assigned_units
        self._log_anchor_change(context)
        if not units:
            return MissionResult(MissionOutcome.ACTIVE, "no_units_assigned")

        moved = False
        for unit in units:
            if unit.position.distance_to(self.target) <= self.arrival_radius:
                continue
            context.commands.safe_path_to(
                mission_id=self.mission_id,
                unit_tag=unit.tag,
                target=self.target,
                success_at_distance=self.arrival_radius,
                # A standing responsibility is always the lowest-priority
                # claim on a unit -- it must never look "busy" to other
                # planners the way an active patrol or engagement does.
                keep_available=True,
            )
            moved = True

        return MissionResult(
            MissionOutcome.ACTIVE,
            "moving_to_position" if moved else "holding_position",
        )

    def _log_anchor_change(self, context: MissionContext) -> None:
        if self._last_anchor == self.target:
            return
        previous, self._last_anchor = self._last_anchor, self.target
        self._log.state_changed(
            now=context.attention.world.time,
            state="ANCHORED",
            reason="anchor_changed" if previous is not None else "anchor_assigned",
            mission_id=self.mission_id,
            anchor=[round(float(self.target.x), 1), round(float(self.target.y), 1)],
            previous_anchor=(
                None
                if previous is None
                else [round(float(previous.x), 1), round(float(previous.y), 1)]
            ),
        )

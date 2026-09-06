from __future__ import annotations

from bot.actions.base import Action, ActionContext
from bot.actions.models import ActionOutcome, ActionStatus
from bot.attention.models import AttentionSnapshot, MissionSummary
from bot.contracts.commands import ActionCommands
from bot.contracts.logging import BotLogger
from bot.units.registry import UnitRegistry


class ActionScheduler:
    """Owns action lifecycle; actions cannot add/remove themselves."""

    def __init__(self, *, registry: UnitRegistry, logger: BotLogger) -> None:
        self.registry = registry
        self.logger = logger
        self._actions: dict[str, Action] = {}

    def submit(self, action: Action) -> bool:
        if action.action_id in self._actions:
            return False
        self._actions[action.action_id] = action
        self.logger.event(
            "action.created",
            component="actions.scheduler",
            game_time=0.0,
            data={"action_id": action.action_id, "type": type(action).__name__},
        )
        return True

    def cancel(self, action_id: str, *, reason: str, game_time: float) -> bool:
        action = self._actions.get(action_id)
        if action is None:
            return False
        action.status = ActionStatus.CANCELLED
        action.last_reason = reason
        self.registry.release_action(action_id)
        del self._actions[action_id]
        self._log_finished(action, game_time)
        return True

    def mission_summaries(self) -> tuple[MissionSummary, ...]:
        return tuple(
            MissionSummary(
                action_id=action.action_id,
                action_type=type(action).__name__,
                status=action.status.name,
                priority=action.priority,
                started_at=action.started_at,
                assigned_unit_tags=tuple(
                    unit.tag for unit in self.registry.assigned_to(action.action_id)
                ),
            )
            for action in sorted(
                self._actions.values(), key=lambda item: (-item.priority, item.action_id)
            )
        )

    async def tick(
        self, attention: AttentionSnapshot, *, commands: ActionCommands
    ) -> None:
        self.registry.sync(attention.world.own_units)
        finished: list[str] = []

        for action in sorted(
            self._actions.values(), key=lambda item: (-item.priority, item.action_id)
        ):
            allocation = self.registry.allocate(
                action.action_id, action.requirements(attention)
            )
            if not allocation.requirements_satisfied:
                action.status = ActionStatus.BLOCKED
                action.last_reason = "unit_requirements_not_satisfied"
                continue

            if action.started_at is None:
                action.started_at = attention.world.time
                self.logger.event(
                    "action.started",
                    component="actions.scheduler",
                    game_time=attention.world.time,
                    data={"action_id": action.action_id},
                )

            action.status = ActionStatus.RUNNING
            result = await action.step(
                ActionContext(
                    attention=attention,
                    assigned_units=self.registry.assigned_to(action.action_id),
                    commands=commands,
                    logger=self.logger,
                )
            )
            action.last_reason = result.reason
            action.status = {
                ActionOutcome.RUNNING: ActionStatus.RUNNING,
                ActionOutcome.BLOCKED: ActionStatus.BLOCKED,
                ActionOutcome.COMPLETED: ActionStatus.COMPLETED,
                ActionOutcome.FAILED: ActionStatus.FAILED,
            }[result.outcome]
            if action.status in {ActionStatus.COMPLETED, ActionStatus.FAILED}:
                finished.append(action.action_id)

        for action_id in finished:
            action = self._actions.pop(action_id)
            self.registry.release_action(action_id)
            self._log_finished(action, attention.world.time)

    def _log_finished(self, action: Action, game_time: float) -> None:
        self.logger.event(
            "action.finished",
            component="actions.scheduler",
            game_time=game_time,
            data={
                "action_id": action.action_id,
                "status": action.status.name,
                "reason": action.last_reason,
            },
        )

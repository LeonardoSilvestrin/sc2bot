"""Runtime coordination for Strategy while its objective has no consumers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from bot.ports.logging import BotLogger
from bot.strategy import (
    MacroPostureDirector,
    StrategicDirector,
    StrategySnapshot,
    build_strategy_inputs,
)
from bot.world.awareness import AwarenessSnapshot, RelativePosition

COMPONENT = "strategy.director"


@dataclass(slots=True)
class StrategyShadow:
    """Update and log Strategy without exposing its objective to gameplay.

    The returned Awareness copy carries the legacy posture existing consumers
    already expect.  That compatibility policy is now evaluated by Strategy;
    the new ``StrategySnapshot.objective`` remains observation-only.
    """

    logger: BotLogger
    director: StrategicDirector = field(default_factory=StrategicDirector)
    legacy_posture: MacroPostureDirector = field(
        default_factory=MacroPostureDirector
    )
    log_interval_seconds: float = 10.0
    _last_logged_at: float = field(default=float("-inf"), init=False, repr=False)

    @property
    def snapshot(self) -> StrategySnapshot | None:
        return self.director.snapshot

    def update(self, awareness: AwarenessSnapshot) -> AwarenessSnapshot:
        previous = self.director.snapshot
        strategy = self.director.update(
            build_strategy_inputs(awareness), awareness.updated_at
        )
        posture = self.legacy_posture.update(
            now=awareness.updated_at,
            workers=awareness.economy.own_workers,
            townhalls=awareness.economy.own_bases,
            own_combat=awareness.relative_strength.own_combat_units,
            strength_is_stably_ahead=(
                awareness.army.relative.stable_state is RelativePosition.AHEAD
            ),
            nearby_enemy_combat=(
                awareness.threat.near_own_base_enemy_combat_units
            ),
        )
        if strategy is not previous and self._should_log(strategy, previous):
            self._log(strategy, previous)
        return replace(awareness, macro_posture=posture)

    def _should_log(
        self,
        current: StrategySnapshot,
        previous: StrategySnapshot | None,
    ) -> bool:
        changed = previous is None or current.objective is not previous.objective
        periodic = (
            current.game_time - self._last_logged_at >= self.log_interval_seconds
        )
        return changed or periodic

    def _log(
        self,
        current: StrategySnapshot,
        previous: StrategySnapshot | None,
    ) -> None:
        self._last_logged_at = current.game_time
        inputs = current.inputs
        serialized_inputs = {
            "military_edge": round(inputs.military_edge, 3),
            "economic_edge": round(inputs.economic_edge, 3),
            "territory_edge": round(inputs.territory_edge, 3),
            "immediate_threat": round(inputs.immediate_threat, 3),
            "base_exposure": round(inputs.base_exposure, 3),
            "knowledge_confidence": round(inputs.knowledge_confidence, 3),
        }
        reason = _transition_reason(current, previous)
        self.logger.event(
            "strategy.updated",
            component=COMPONENT,
            game_time=current.game_time,
            data={
                "objective": current.objective.name,
                "previous_objective": (
                    None
                    if current.previous_objective is None
                    else current.previous_objective.name
                ),
                "leader": current.leader.name,
                "scores": {
                    item.objective.name: round(item.score, 3)
                    for item in current.assessments
                },
                "inputs": serialized_inputs,
                **serialized_inputs,
                "confidence": round(current.confidence, 3),
                "time_in_objective": round(current.time_in_objective, 3),
                "transition_reason": reason,
                "reason": reason,
                "shadow": True,
                "mode": "shadow",
            },
        )


def _transition_reason(
    current: StrategySnapshot, previous: StrategySnapshot | None
) -> str:
    if previous is None:
        return "initial_objective"
    if current.objective is not previous.objective:
        return f"score_margin_selected_{current.objective.name.lower()}"
    if current.leader is not current.objective:
        return f"hysteresis_holds_over_{current.leader.name.lower()}"
    return "objective_remains_leader"


__all__ = ["StrategyShadow"]

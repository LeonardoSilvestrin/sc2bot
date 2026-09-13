"""Runtime coordination for Strategy: update it, publish it, log it."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from bot.ports.logging import BotLogger
from bot.strategy import (
    IntentConfig,
    MacroPostureDirector,
    SpatialPolicyConfig,
    StrategicContext,
    StrategicDirector,
    StrategySnapshot,
    build_strategy_inputs,
    derive_control_objectives,
    derive_intent,
)
from bot.world.awareness import AwarenessSnapshot, RelativePosition

COMPONENT = "strategy.director"


@dataclass(slots=True)
class StrategyRuntime:
    """Update Strategy once per frame and publish what behaviors consume.

    Each new ``StrategySnapshot`` becomes the frame's ``StrategicContext``:
    the intent, and the control objectives that intent asks for over the
    Awareness snapshot it was computed from -- what planners and the Mission
    Policy read. The returned Awareness copy still carries the legacy
    ``MacroPosture`` macro depends on; that field is compatibility transport
    only.
    """

    logger: BotLogger
    director: StrategicDirector = field(default_factory=StrategicDirector)
    intent_config: IntentConfig = field(default_factory=IntentConfig)
    spatial_config: SpatialPolicyConfig = field(default_factory=SpatialPolicyConfig)
    legacy_posture: MacroPostureDirector = field(
        default_factory=MacroPostureDirector
    )
    log_interval_seconds: float = 10.0
    _last_logged_at: float = field(default=float("-inf"), init=False, repr=False)
    _context: StrategicContext = field(
        default_factory=StrategicContext.neutral, init=False, repr=False
    )

    @property
    def snapshot(self) -> StrategySnapshot | None:
        return self.director.snapshot

    @property
    def context(self) -> StrategicContext:
        """The latest prescriptions; neutral before the first update."""

        return self._context

    def update(self, awareness: AwarenessSnapshot) -> AwarenessSnapshot:
        previous = self.director.snapshot
        strategy = self.director.update(
            build_strategy_inputs(awareness), awareness.updated_at
        )
        if strategy is not previous:
            intent = derive_intent(strategy, self.intent_config)
            self._context = StrategicContext(
                intent=intent,
                spatial=derive_control_objectives(
                    intent, awareness, self.spatial_config
                ),
                updated_at=strategy.game_time,
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
                # The objective now drives gameplay through the intent.
                "shadow": False,
                "mode": "live",
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


__all__ = ["COMPONENT", "StrategyRuntime"]

"""Runtime coordination for Strategy: update it, publish it, log it."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

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

    Each new ``StrategySnapshot`` is spelled out as a candidate
    ``StrategicContext``: the intent, and the control objectives that intent
    asks for over the Awareness snapshot it was computed from. Only a
    materially different context is published, under the next revision; an
    identical one keeps the current revision, so a revision names exactly one
    set of prescriptions.

    ``record_context`` persists the published context exactly, once per
    revision, as ``strategy.context``; the frame calls it before the Mission
    Policy's first decision under that revision. ``strategy.updated`` stays
    the change/heartbeat summary of the objective.

    The returned Awareness copy still carries the legacy ``MacroPosture``
    macro depends on; that field is compatibility transport only.
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
    # The snapshot the published context was derived from; None while neutral.
    _context_snapshot: StrategySnapshot | None = field(
        default=None, init=False, repr=False
    )
    _recorded_revision: int | None = field(default=None, init=False, repr=False)

    @property
    def snapshot(self) -> StrategySnapshot | None:
        return self.director.snapshot

    @property
    def context(self) -> StrategicContext:
        """The latest prescriptions; neutral (revision 0) before the first
        update."""

        return self._context

    def update(self, awareness: AwarenessSnapshot) -> AwarenessSnapshot:
        previous = self.director.snapshot
        strategy = self.director.update(
            build_strategy_inputs(awareness), awareness.updated_at
        )
        if strategy is not previous:
            intent = derive_intent(strategy, self.intent_config)
            candidate = StrategicContext(
                intent=intent,
                spatial=derive_control_objectives(
                    intent, awareness, self.spatial_config
                ),
                updated_at=strategy.game_time,
                revision=self._context.revision + 1,
            )
            if self._context_snapshot is None or not candidate.materially_equals(
                self._context
            ):
                self._context = candidate
                self._context_snapshot = strategy
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

    def record_context(self) -> None:
        """Persist the published context, once per revision, exactly.

        The record is complete: the objective and every assessment with its
        score contributions, the inputs, the intent and every control
        objective. A later revision's record replaces it wholesale, so an
        objective missing from it is no longer wanted.
        """

        context = self._context
        if context.revision == self._recorded_revision:
            return
        self._recorded_revision = context.revision
        snapshot = self._context_snapshot
        self.logger.event(
            "strategy.context",
            component=COMPONENT,
            game_time=context.updated_at,
            data={
                "revision": context.revision,
                "updated_at": context.updated_at,
                "objective": None if snapshot is None else snapshot.objective.name,
                "leader": None if snapshot is None else snapshot.leader.name,
                "confidence": None if snapshot is None else snapshot.confidence,
                "inputs": None if snapshot is None else _inputs(snapshot),
                "assessments": (
                    [] if snapshot is None else _assessments(snapshot)
                ),
                "intent": context.intent.as_dict(),
                "control_objectives": [
                    objective.log_fields()
                    for objective in context.spatial.objectives
                ],
            },
        )

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
        serialized_inputs = _inputs(current)
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
                    item.objective.name: item.score for item in current.assessments
                },
                "inputs": serialized_inputs,
                **serialized_inputs,
                "confidence": current.confidence,
                "time_in_objective": current.time_in_objective,
                "transition_reason": reason,
                "reason": reason,
                "context_revision": self._context.revision,
                # The objective now drives gameplay through the intent.
                "shadow": False,
                "mode": "live",
            },
        )


def _inputs(snapshot: StrategySnapshot) -> dict[str, float]:
    inputs = snapshot.inputs
    return {
        "military_edge": inputs.military_edge,
        "economic_edge": inputs.economic_edge,
        "territory_edge": inputs.territory_edge,
        "immediate_threat": inputs.immediate_threat,
        "base_exposure": inputs.base_exposure,
        "knowledge_confidence": inputs.knowledge_confidence,
    }


def _assessments(snapshot: StrategySnapshot) -> list[dict[str, Any]]:
    return [
        {
            "objective": item.objective.name,
            "score": item.score,
            "raw_score": item.raw_score,
            "contributions": {
                contribution.signal: contribution.contribution
                for contribution in item.contributions
            },
        }
        for item in snapshot.assessments
    ]


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

"""The Mission Policy at runtime: every planner's candidates, one scale.

Planners describe opportunities (``MissionCandidate``); this evaluates each
under the frame's ``StrategicContext`` with ``bot.strategy.evaluate_mission``,
logs every evaluation -- a rejection as much as an acceptance -- and hands
``MissionController`` ordinary proposals for the viable ones only, carrying
the final priority. Neither side learns about the other: planners never see a
priority, and the engine never sees a signal, an intent or a rejected
candidate.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from bot.behavior.contracts import MissionCandidate
from bot.engine.missions.models import MissionProposal
from bot.ports.logging import BotLogger
from bot.strategy import (
    MissionEvaluation,
    MissionPolicyConfig,
    StrategicContext,
    evaluate_mission,
)

COMPONENT = "strategy.mission_policy"


@dataclass(slots=True)
class MissionRanker:
    """Evaluates candidates, logs each evaluation, proposes the viable ones.

    ``mission.evaluated`` is written for every candidate, viable or rejected,
    under its ``proposal_id`` -- the join to the controller's ``proposal_*``
    events. Planners propose on cadences seconds apart, so this is one line
    per decision, not per frame, and is never change-gated.
    """

    logger: BotLogger | None = None
    config: MissionPolicyConfig = field(default_factory=MissionPolicyConfig)
    # The latest evaluation per deduplication key (tests, telemetry).
    last_evaluations: dict[str, MissionEvaluation] = field(
        default_factory=dict, init=False, repr=False
    )

    def rank(
        self,
        candidates: Iterable[MissionCandidate],
        strategy: StrategicContext | None = None,
    ) -> tuple[MissionProposal, ...]:
        context = strategy or StrategicContext.neutral()
        proposals: list[MissionProposal] = []
        for candidate in candidates:
            signals = candidate.signals
            evaluation = evaluate_mission(
                signals,
                context.intent,
                need=context.need_for(
                    None if signals.control is None else signals.control.objective_id
                ),
                config=self.config,
            )
            self.last_evaluations[candidate.draft.deduplication_key] = evaluation
            self._log(candidate, evaluation)
            if evaluation.priority is not None:
                proposals.append(candidate.ranked(evaluation.priority))
        return tuple(proposals)

    def _log(self, candidate: MissionCandidate, evaluation: MissionEvaluation) -> None:
        if self.logger is None:
            return
        draft = candidate.draft
        self.logger.event(
            "mission.evaluated",
            component=COMPONENT,
            game_time=draft.created_at,
            data={
                "proposal_id": draft.proposal_id,
                "deduplication_key": draft.deduplication_key,
                "planner": draft.planner,
                "mission_kind": draft.kind.name,
                "target_key": draft.target_key,
                "target": [float(draft.target.x), float(draft.target.y)],
                "viable": evaluation.viable,
                "reason": evaluation.reason,
                "priority": evaluation.priority,
                "signals": candidate.signals.log_fields(),
                "evaluation": evaluation.log_fields(),
            },
        )


def rank_candidates(
    candidates: Iterable[MissionCandidate],
    strategy: StrategicContext | None = None,
) -> tuple[MissionProposal, ...]:
    """Rank with the default policy and no logging (tests, tools)."""

    return MissionRanker().rank(candidates, strategy)


__all__ = ["COMPONENT", "MissionRanker", "rank_candidates"]

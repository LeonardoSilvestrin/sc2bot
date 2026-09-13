"""The Mission Policy at runtime: every planner's candidates, one scale.

Planners describe opportunities (``MissionCandidate``); this ranks them all
under the frame's ``StrategicContext`` with ``bot.strategy.score_mission``
and hands ``MissionController`` ordinary proposals carrying the final
priority. Neither side learns about the other: planners never see a
priority, and the engine never sees a signal or an intent.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from bot.behavior.contracts import MissionCandidate
from bot.engine.missions.models import MissionProposal
from bot.ports.logging import BotLogger
from bot.strategy import (
    MissionPolicyConfig,
    MissionRanking,
    StrategicContext,
    score_mission,
)

from .telemetry.gate import ChangeGate

COMPONENT = "strategy.mission_policy"


@dataclass(slots=True)
class MissionRanker:
    """Ranks candidates and logs why, once per change of each responsibility.

    ``mission.candidate`` (the planner's signals) and ``mission.ranked`` (the
    policy's breakdown) go out together whenever a deduplication key's
    signals or priority change, and at least every ``log_heartbeat`` seconds.
    """

    logger: BotLogger | None = None
    config: MissionPolicyConfig = field(default_factory=MissionPolicyConfig)
    log_heartbeat: float = 30.0
    last_rankings: dict[str, MissionRanking] = field(
        default_factory=dict, init=False, repr=False
    )
    _gates: dict[str, ChangeGate] = field(default_factory=dict, init=False, repr=False)

    def rank(
        self,
        candidates: Iterable[MissionCandidate],
        strategy: StrategicContext | None = None,
    ) -> tuple[MissionProposal, ...]:
        context = strategy or StrategicContext.neutral()
        proposals: list[MissionProposal] = []
        for candidate in candidates:
            signals = candidate.signals
            ranking = score_mission(
                signals,
                context.intent,
                need=context.need_for(signals.control_objective),
                config=self.config,
            )
            self.last_rankings[candidate.draft.deduplication_key] = ranking
            self._log(candidate, ranking)
            proposals.append(candidate.ranked(ranking.priority))
        return tuple(proposals)

    def _log(self, candidate: MissionCandidate, ranking: MissionRanking) -> None:
        if self.logger is None:
            return
        draft = candidate.draft
        signals = candidate.signals.log_fields()
        signature = (
            ranking.priority,
            draft.target_key,
            tuple(
                (name, round(value, 2) if isinstance(value, float) else value)
                for name, value in sorted(signals.items())
            ),
        )
        gate = self._gates.setdefault(
            draft.deduplication_key, ChangeGate(heartbeat=self.log_heartbeat)
        )
        if not gate.admit(signature, now=draft.created_at):
            return
        common = {
            "planner": draft.planner,
            "proposal_id": draft.proposal_id,
            "deduplication_key": draft.deduplication_key,
            "mission_kind": draft.kind.name,
            "target_key": draft.target_key,
            "target": [
                round(float(draft.target.x), 1),
                round(float(draft.target.y), 1),
            ],
        }
        self.logger.event(
            "mission.candidate",
            component=COMPONENT,
            game_time=draft.created_at,
            data={**common, **signals},
        )
        self.logger.event(
            "mission.ranked",
            component=COMPONENT,
            game_time=draft.created_at,
            data={**common, **ranking.log_fields()},
        )


def rank_candidates(
    candidates: Iterable[MissionCandidate],
    strategy: StrategicContext | None = None,
) -> tuple[MissionProposal, ...]:
    """Rank with the default policy and no logging (tests, tools)."""

    return MissionRanker().rank(candidates, strategy)


__all__ = ["COMPONENT", "MissionRanker", "rank_candidates"]

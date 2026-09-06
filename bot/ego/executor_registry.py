from __future__ import annotations

from collections.abc import Callable, Mapping

from bot.ego.models import Mission, MissionKind
from bot.executors import MissionExecutor, ScoutExecutor

MissionExecutorFactory = Callable[[Mission, float], MissionExecutor]


def _build_scout_executor(mission: Mission, now: float) -> MissionExecutor:
    return ScoutExecutor(
        mission_id=mission.mission_id,
        target_key=mission.proposal.target_key,
        target=mission.proposal.target,
        started_at=now,
    )


DEFAULT_EXECUTOR_FACTORIES: Mapping[MissionKind, MissionExecutorFactory] = {
    MissionKind.SCOUT: _build_scout_executor,
}

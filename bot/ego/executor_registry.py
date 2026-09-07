from __future__ import annotations

from collections.abc import Callable, Mapping

from bot.ego.models import Mission, MissionKind
from bot.executors import (
    DefendBaseExecutor,
    MissionExecutor,
    ScoutExecutor,
    WorkerLineHarassExecutor,
)

MissionExecutorFactory = Callable[[Mission, float], MissionExecutor]


def _build_scout_executor(mission: Mission, now: float) -> MissionExecutor:
    return ScoutExecutor(
        mission_id=mission.mission_id,
        target_key=mission.proposal.target_key,
        target=mission.proposal.target,
        started_at=now,
    )


def _build_worker_line_harass_executor(mission: Mission, now: float) -> MissionExecutor:
    return WorkerLineHarassExecutor(
        mission_id=mission.mission_id,
        target_key=mission.proposal.target_key,
        target=mission.proposal.target,
        started_at=now,
    )


def _build_defend_base_executor(mission: Mission, now: float) -> MissionExecutor:
    return DefendBaseExecutor(
        mission_id=mission.mission_id,
        target_key=mission.proposal.target_key,
        target=mission.proposal.target,
        started_at=now,
    )


DEFAULT_EXECUTOR_FACTORIES: Mapping[MissionKind, MissionExecutorFactory] = {
    MissionKind.SCOUT: _build_scout_executor,
    MissionKind.HARASS: _build_worker_line_harass_executor,
    MissionKind.DEFENSE: _build_defend_base_executor,
}

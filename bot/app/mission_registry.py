from __future__ import annotations

from collections.abc import Mapping

from bot.behavior.army import DispositionPlannerConfig, PositioningExecutor
from bot.behavior.defense import DefendBaseExecutor
from bot.behavior.harass import CloakedBansheeHarassExecutor, WorkerLineHarassExecutor
from bot.behavior.map_control import MapControlExecutor
from bot.behavior.scouting import ScoutExecutor
from bot.engine.missions.execution import (
    MissionExecutor,
    MissionExecutorFactory,
)
from bot.engine.missions.models import Mission, MissionKind


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


def _build_cloaked_banshee_harass_executor(
    mission: Mission, now: float
) -> MissionExecutor:
    return CloakedBansheeHarassExecutor(
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


def _build_map_control_executor(mission: Mission, now: float) -> MissionExecutor:
    return MapControlExecutor(
        mission_id=mission.mission_id,
        target_key=mission.proposal.target_key,
        target=mission.proposal.target,
        started_at=now,
    )


def _build_positioning_executor(
    mission: Mission, now: float, *, arrival_radius: float
) -> MissionExecutor:
    return PositioningExecutor(
        mission_id=mission.mission_id,
        target_key=mission.proposal.target_key,
        target=mission.proposal.target,
        started_at=now,
        arrival_radius=arrival_radius,
    )


def build_executor_factories(
    *, disposition_config: DispositionPlannerConfig | None = None
) -> Mapping[MissionKind, MissionExecutorFactory]:
    """Executor factories, parameterized by the live ``DispositionPlannerConfig``.

    ``PositioningExecutor.arrival_radius`` must track
    ``DispositionPlannerConfig.arrival_radius`` rather than silently using
    the executor's own default -- see ``DEFAULT_EXECUTOR_FACTORIES`` for the
    default-config convenience binding most tests use.
    """

    config = disposition_config or DispositionPlannerConfig()
    arrival_radius = config.arrival_radius
    return {
        MissionKind.SCOUT: _build_scout_executor,
        MissionKind.HARASS: _build_worker_line_harass_executor,
        MissionKind.AIR_HARASS: _build_cloaked_banshee_harass_executor,
        MissionKind.DEFENSE: _build_defend_base_executor,
        MissionKind.MAP_CONTROL: _build_map_control_executor,
        MissionKind.HOLD_RALLY: (
            lambda mission, now: PositioningExecutor(
                mission_id=mission.mission_id,
                target_key=mission.proposal.target_key,
                target=mission.proposal.target,
                started_at=now,
                arrival_radius=config.arrival_radius,
            )
        ),
        MissionKind.POSITION: (
            lambda mission, now: _build_positioning_executor(
                mission, now, arrival_radius=arrival_radius
            )
        ),
    }


DEFAULT_EXECUTOR_FACTORIES: Mapping[MissionKind, MissionExecutorFactory] = (
    build_executor_factories()
)

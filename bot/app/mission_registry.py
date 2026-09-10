"""Which executor runs which mission kind.

The only place that knows the mapping. `MissionController` is handed this
table and never learns what a kind means, which is what lets a new behavior
be added without touching the controller's internals.

Each factory binds its executor to the same config its planner uses, so
tuning a behavior in one place tunes both halves of it.
"""

from __future__ import annotations

from collections.abc import Mapping

from bot.behavior.defense import DefendBaseExecutor, DefenseConfig
from bot.behavior.harass.banshee import BansheeHarassConfig, BansheeHarassExecutor
from bot.behavior.harass.reaper import ReaperHarassConfig, ReaperHarassExecutor
from bot.behavior.map_control import MapControlConfig, MapControlExecutor
from bot.behavior.scouting import IntelConfig, ScoutExecutor
from bot.behavior.standing import StandingConfig, StandingExecutor
from bot.engine.missions.execution import (
    MissionExecutor,
    MissionExecutorFactory,
)
from bot.engine.missions.models import Mission, MissionKind
from bot.ports.logging import BotLogger


def build_executor_factories(
    *,
    standing_config: StandingConfig | None = None,
    banshee_config: BansheeHarassConfig | None = None,
    reaper_config: ReaperHarassConfig | None = None,
    defense_config: DefenseConfig | None = None,
    map_control_config: MapControlConfig | None = None,
    intel_config: IntelConfig | None = None,
    logger: BotLogger | None = None,
) -> Mapping[MissionKind, MissionExecutorFactory]:
    """Executor factories bound to the live behavior configs.

    ``DEFAULT_EXECUTOR_FACTORIES`` is the default-config convenience binding
    most tests use.
    """

    standing = standing_config or StandingConfig()
    banshee = banshee_config or BansheeHarassConfig()
    reaper = reaper_config or ReaperHarassConfig()
    defense = defense_config or DefenseConfig()
    map_control = map_control_config or MapControlConfig()
    intel = intel_config or IntelConfig()

    def build_scout(mission: Mission, now: float) -> MissionExecutor:
        return ScoutExecutor(
            mission_id=mission.mission_id,
            target_key=mission.proposal.target_key,
            target=mission.proposal.target,
            started_at=now,
            config=intel,
        )

    def build_defense(mission: Mission, now: float) -> MissionExecutor:
        return DefendBaseExecutor(
            mission_id=mission.mission_id,
            target_key=mission.proposal.target_key,
            target=mission.proposal.target,
            started_at=now,
            config=defense,
        )

    def build_map_control(mission: Mission, now: float) -> MissionExecutor:
        return MapControlExecutor(
            mission_id=mission.mission_id,
            target_key=mission.proposal.target_key,
            target=mission.proposal.target,
            started_at=now,
            config=map_control,
            logger=logger,
        )

    def build_standing(mission: Mission, now: float) -> MissionExecutor:
        return StandingExecutor(
            mission_id=mission.mission_id,
            target_key=mission.proposal.target_key,
            target=mission.proposal.target,
            started_at=now,
            arrival_radius=standing.arrival_radius,
            logger=logger,
        )

    def build_banshee_harass(mission: Mission, now: float) -> MissionExecutor:
        return BansheeHarassExecutor(
            mission_id=mission.mission_id,
            target_key=mission.proposal.target_key,
            target=mission.proposal.target,
            started_at=now,
            config=banshee,
            logger=logger,
        )

    def build_reaper_harass(mission: Mission, now: float) -> MissionExecutor:
        return ReaperHarassExecutor(
            mission_id=mission.mission_id,
            target_key=mission.proposal.target_key,
            target=mission.proposal.target,
            started_at=now,
            config=reaper,
        )

    return {
        MissionKind.SCOUT: build_scout,
        MissionKind.HARASS: build_reaper_harass,
        MissionKind.AIR_HARASS: build_banshee_harass,
        MissionKind.DEFENSE: build_defense,
        MissionKind.MAP_CONTROL: build_map_control,
        MissionKind.HOLD_RALLY: build_standing,
        MissionKind.POSITION: build_standing,
    }


DEFAULT_EXECUTOR_FACTORIES: Mapping[MissionKind, MissionExecutorFactory] = (
    build_executor_factories()
)

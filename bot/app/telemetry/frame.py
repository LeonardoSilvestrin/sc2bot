from __future__ import annotations

from bot.behavior.standing import StandingPlanner
from bot.engine.missions import MissionController
from bot.ports.logging import BotLogger
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot

from .belief import BeliefTelemetry
from .build_order import BuildOrderTelemetry
from .enemy import EnemyTelemetry
from .standing import StandingTelemetry
from .territory import TerritoryTelemetry
from .world import WorldSnapshotTelemetry


class FrameTelemetry:
    """Runs every end-of-frame reporter, in the order their events are logged."""

    def __init__(
        self,
        *,
        logger: BotLogger,
        missions: MissionController,
        standing_planner: StandingPlanner,
    ) -> None:
        self._missions = missions
        self._build_order = BuildOrderTelemetry(logger=logger)
        self._enemy = EnemyTelemetry(logger=logger)
        self._belief = BeliefTelemetry(logger=logger)
        self._territory = TerritoryTelemetry(logger=logger)
        self._world = WorldSnapshotTelemetry(logger=logger)
        self._standing = StandingTelemetry(
            logger=logger, missions=missions, standing_planner=standing_planner
        )

    def report(
        self, bot, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> None:
        game_time = attention.world.time
        self._build_order.report(bot, game_time=game_time)
        self._enemy.report(awareness, game_time=game_time)
        self._belief.report(awareness, game_time=game_time)
        self._territory.report(awareness, game_time=game_time)
        self._world.report(attention, awareness, missions=self._missions.snapshots())
        self._standing.report(attention)

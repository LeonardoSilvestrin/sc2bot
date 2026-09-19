"""LOGS: how the bot explains itself.

`Logs` bundles the three observers of a frame -- the JSONL event log, the SVG
field snapshots and the in-game overlay. None of them may change a decision,
and none of them may stop a match.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter

from bot.attention import AttentionState, MapView
from bot.awareness import AwarenessState
from bot.body.behaviors.attack import MicroReport
from bot.body.behaviors.detection import DetectionReport
from bot.body.behaviors.economy import SpawnMode
from bot.body.behaviors.sensor_towers import SensorTowerReport
from bot.body.engine import EngineResult
from bot.ego.missions import MissionView
from bot.ego.planners import (
    EconomyPlan,
    IntelPlan,
    Proposal,
    StructurePlan,
)
from bot.ego.planners.map_control import MapControlPlan
from bot.ego.planners.offense import OffensePlan
from bot.ego.strategy import StrategyState

from .jsonl import BotLogger, ChangeGate, JsonlLogger, NullLogger
from .overlay import Overlay, OverlayConfig
from .snapshot import SnapshotConfig, SnapshotExporter, render_svg
from .telemetry import Telemetry

__all__ = [
    "BotLogger",
    "ChangeGate",
    "JsonlLogger",
    "Logs",
    "NullLogger",
    "Overlay",
    "OverlayConfig",
    "SnapshotConfig",
    "SnapshotExporter",
    "Telemetry",
    "render_svg",
]


class Logs:
    def __init__(
        self,
        logger: BotLogger | None = None,
        *,
        overlay: OverlayConfig | None = None,
        snapshots: SnapshotConfig | None = None,
        snapshot_directory: Path | None = None,
    ) -> None:
        self.logger = logger or NullLogger()
        self.telemetry = Telemetry(self.logger)
        self.overlay = Overlay(overlay)
        self.snapshots = SnapshotExporter(
            config=snapshots, directory=snapshot_directory, logger=self.logger
        )
        self._last_ms = 0.0

    def game_started(self, bot, map_view: MapView, configs: Mapping[str, object]) -> None:
        runner = getattr(bot, "build_order_runner", None)
        self.telemetry.started(
            time=float(bot.time),
            map_view=map_view,
            race=str(getattr(bot, "race", "")),
            enemy_race=str(getattr(bot, "enemy_race", "")),
            opening=str(getattr(runner, "chosen_opening", "") or "") or None,
            configs=configs,
        )

    def record(
        self,
        bot,
        attention: AttentionState,
        awareness: AwarenessState,
        strategy: StrategyState,
        map_control: MapControlPlan,
        offense: OffensePlan,
        proposals: Sequence[Proposal],
        economy: EconomyPlan,
        structures: StructurePlan,
        result: EngineResult,
        spawn: SpawnMode,
        micro: MicroReport,
        timings: Mapping[str, float],
        *,
        intel: IntelPlan | None = None,
        detected: DetectionReport | None = None,
        tower_building: SensorTowerReport | None = None,
        infrastructure: tuple[str, ...] = (),
        missions: Sequence[MissionView] = (),
    ) -> None:
        started = perf_counter()
        self.logger.begin_frame(attention.iteration)
        try:
            self.telemetry.record(
                attention,
                awareness,
                strategy,
                map_control,
                offense,
                proposals,
                economy,
                structures,
                result,
                spawn,
                micro,
                {**timings, "logs": self._last_ms},
                intel=intel,
                detected=detected,
                tower_building=tower_building,
                infrastructure=infrastructure,
                missions=missions,
            )
            self.snapshots.capture(attention, awareness, strategy, map_control, result)
            self.overlay.render(bot, attention, awareness, strategy, map_control, result)
        finally:
            self.logger.end_frame()
            self._last_ms = (perf_counter() - started) * 1000.0

    def game_ended(self, time: float, result) -> None:
        self.telemetry.ended(time=time, result=str(result))
        self.logger.close()

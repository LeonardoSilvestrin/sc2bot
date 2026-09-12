"""Composition root: every long-lived object of one game, wired once.

Plain constructors, no container -- this is the only module that knows which
concrete observer, planners, controllers and diagnostics a game runs with.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from bot.adapters.ares import AresWorldObserver
from bot.app.mission_registry import build_executor_factories
from bot.behavior.defense import DefenseConfig, DefensePlanner
from bot.behavior.harass.banshee import BansheeHarassConfig, BansheeHarassPlanner
from bot.behavior.harass.reaper import ReaperHarassConfig, ReaperHarassPlanner
from bot.behavior.map_control import MapControlConfig, MapControlPlanner
from bot.behavior.scouting import (
    IntelConfig,
    IntelPlanner,
    ScoutingVisionConfig,
    ScoutingVisionRequester,
)
from bot.behavior.standing import StandingConfig, StandingPlanner
from bot.engine.economy import EconomyController
from bot.engine.missions import MissionController
from bot.engine.services import (
    BehaviorServices,
    ScanProvider,
    ScanProviderConfig,
    VisionService,
    VisionServiceConfig,
)
from bot.macro import MacroDiagnostics, MacroPlanner, MacroPlannerConfig
from bot.ports.logging import BotLogger
from bot.world.awareness import AwarenessService, SpatialModelConfig

from .debug import SpatialDebugConfig, SpatialDebugView
from .frame import FrameProcessor
from .opening import OpeningSelector
from .telemetry import FrameTelemetry


@dataclass(frozen=True)
class BotComposition:
    opening: OpeningSelector
    frame: FrameProcessor
    # The two domains' admission points, kept reachable for inspection
    # (tests, debugging); `frame` is what drives them.
    missions: MissionController
    macro_planner: MacroPlanner


def compose_bot(
    *,
    logger: BotLogger,
    intel_config: IntelConfig | None = None,
    scouting_vision_config: ScoutingVisionConfig | None = None,
    vision_service_config: VisionServiceConfig | None = None,
    scan_provider_config: ScanProviderConfig | None = None,
    banshee_harass_config: BansheeHarassConfig | None = None,
    reaper_harass_config: ReaperHarassConfig | None = None,
    defense_config: DefenseConfig | None = None,
    macro_config: MacroPlannerConfig | None = None,
    map_control_config: MapControlConfig | None = None,
    standing_config: StandingConfig | None = None,
    spatial_model_config: SpatialModelConfig | None = None,
    spatial_sample_spacing: int = 10,
    spatial_debug_config: SpatialDebugConfig | None = None,
    rng: random.Random | None = None,
) -> BotComposition:
    rng = rng or random.Random()
    intel_config = intel_config or IntelConfig()
    scouting_vision_config = scouting_vision_config or ScoutingVisionConfig()
    banshee_harass_config = banshee_harass_config or BansheeHarassConfig()
    reaper_harass_config = reaper_harass_config or ReaperHarassConfig()
    defense_config = defense_config or DefenseConfig()
    map_control_config = map_control_config or MapControlConfig()
    standing_config = standing_config or StandingConfig()

    # Read side.
    world_observer = AresWorldObserver(spatial_sample_spacing=spatial_sample_spacing)
    awareness = AwarenessService(
        location_stale_after=intel_config.location_stale_after,
        spatial_model_config=spatial_model_config,
        logger=logger,
    )

    # Capabilities several behaviors share.
    vision = VisionService(
        provider=ScanProvider(
            config=scan_provider_config or ScanProviderConfig(), logger=logger
        ),
        config=vision_service_config or VisionServiceConfig(),
        logger=logger,
    )
    services = BehaviorServices(vision=vision)

    # Behavior domain: planners propose missions for units on the map.
    intel_planner = IntelPlanner(config=intel_config, logger=logger)
    scouting_vision = ScoutingVisionRequester(
        services=services,
        config=scouting_vision_config,
        logger=logger,
    )
    banshee_harass_planner = BansheeHarassPlanner(
        config=banshee_harass_config, logger=logger
    )
    reaper_harass_planner = ReaperHarassPlanner(
        config=reaper_harass_config, logger=logger
    )
    defense_planner = DefensePlanner(
        config=defense_config,
        logger=logger,
        services=services,
    )
    map_control_planner = MapControlPlanner(config=map_control_config, logger=logger)
    standing_planner = StandingPlanner(config=standing_config, logger=logger)
    mission_planners = (
        intel_planner,
        reaper_harass_planner,
        banshee_harass_planner,
        defense_planner,
        map_control_planner,
        # The default behavior last: its standing proposal should not
        # shadow anything above in reasoning about this tick's proposal
        # list, though admission order does not actually depend on list
        # order (MissionController sorts live missions by priority every
        # tick regardless).
        standing_planner,
    )
    missions = MissionController(
        logger=logger,
        executor_factories=build_executor_factories(
            standing_config=standing_config,
            banshee_config=banshee_harass_config,
            reaper_config=reaper_harass_config,
            defense_config=defense_config,
            map_control_config=map_control_config,
            intel_config=intel_config,
            logger=logger,
        ),
    )

    # Macro domain: what to spend on, admitted against the bank. The
    # opening is unknown until the Ares build runner resolves it, so the
    # planner follows it -- unless a caller pins `macro_config` (tests).
    macro_planner = MacroPlanner(
        config=macro_config or MacroPlannerConfig(),
        follow_opening=macro_config is None,
    )
    economy = EconomyController(logger=logger)
    macro_diagnostics = MacroDiagnostics(logger=logger)

    frame = FrameProcessor(
        logger=logger,
        world_observer=world_observer,
        awareness=awareness,
        vision=vision,
        services=services,
        scouting_vision=scouting_vision,
        mission_planners=mission_planners,
        missions=missions,
        macro_planner=macro_planner,
        economy=economy,
        macro_diagnostics=macro_diagnostics,
        telemetry=FrameTelemetry(
            logger=logger, missions=missions, standing_planner=standing_planner
        ),
        spatial_debug=SpatialDebugView(spatial_debug_config),
    )
    return BotComposition(
        opening=OpeningSelector(rng=rng),
        frame=frame,
        missions=missions,
        macro_planner=macro_planner,
    )

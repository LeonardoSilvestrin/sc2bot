from __future__ import annotations

import random

from bot.behavior.defense import DefenseConfig
from bot.behavior.harass.banshee import BansheeHarassConfig
from bot.behavior.harass.reaper import ReaperHarassConfig
from bot.behavior.map_control import MapControlConfig
from bot.behavior.scouting import IntelConfig, ScoutingVisionConfig
from bot.behavior.standing import StandingConfig
from bot.engine.services import ScanProviderConfig, VisionServiceConfig
from bot.macro import MacroPlannerConfig
from bot.ports.logging import BotLogger
from bot.world.awareness import SpatialModelConfig

from .composition import compose_bot
from .debug import SpatialDebugConfig


class BotRuntime:
    """The bot's shell over Ares' game hooks.

    `compose_bot` wires the game's objects once. From then on the runtime
    marks the start and end of the game and hands every frame to
    `FrameProcessor`; it decides nothing strategic itself.
    """

    def __init__(
        self,
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
    ) -> None:
        self.logger = logger
        composition = compose_bot(
            logger=logger,
            intel_config=intel_config,
            scouting_vision_config=scouting_vision_config,
            vision_service_config=vision_service_config,
            scan_provider_config=scan_provider_config,
            banshee_harass_config=banshee_harass_config,
            reaper_harass_config=reaper_harass_config,
            defense_config=defense_config,
            macro_config=macro_config,
            map_control_config=map_control_config,
            standing_config=standing_config,
            spatial_model_config=spatial_model_config,
            spatial_sample_spacing=spatial_sample_spacing,
            spatial_debug_config=spatial_debug_config,
            rng=rng,
        )
        self._opening = composition.opening
        self._frame = composition.frame
        self.missions = composition.missions
        self.macro_planner = composition.macro_planner

    async def on_start(self, bot) -> None:
        await self._opening.choose_and_announce(bot)
        self.logger.event(
            "game.started",
            component="app.runtime",
            game_time=float(bot.time),
            data={"map": str(bot.game_info.map_name)},
        )

    async def on_step(self, bot, *, iteration: int) -> None:
        await self._frame.process(bot, iteration=iteration)

    async def on_end(self, bot, *, result) -> None:
        self.logger.event(
            "game.ended",
            component="app.runtime",
            game_time=float(bot.time),
            data={"result": str(result)},
        )
        self.logger.close()

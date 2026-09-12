from __future__ import annotations

from bot.adapters.ares import (
    AresEconomyCommands,
    AresMissionCommands,
    AresVisionCommands,
    AresWorldObserver,
    register_baseline_behaviors,
)
from bot.behavior.contracts import BehaviorPlanner
from bot.behavior.scouting import ScoutingVisionRequester
from bot.engine.economy import EconomyController
from bot.engine.missions import MissionController
from bot.engine.services import BehaviorServices, VisionService
from bot.macro import MacroDiagnostics, MacroPlanner
from bot.ports.logging import BotLogger
from bot.world.attention import AttentionService, AttentionSnapshot
from bot.world.awareness import AwarenessService, AwarenessSnapshot

from .telemetry import FrameTelemetry


class FrameProcessor:
    """Carries one game frame from Ares state to decisions and commands.

    One read side feeds two domains that never learn about each other:
    behavior planners, whose missions ``MissionController`` admits and runs on
    units, and ``MacroPlanner``, whose purchases ``EconomyController`` admits
    against the bank. Diagnostics read the outcome last. The step order is
    behavior, not presentation -- see "Frame lifecycle" in
    ``_botdev/architecture/contracts.md``.
    """

    def __init__(
        self,
        *,
        logger: BotLogger,
        world_observer: AresWorldObserver,
        awareness: AwarenessService,
        vision: VisionService,
        services: BehaviorServices,
        scouting_vision: ScoutingVisionRequester,
        mission_planners: tuple[BehaviorPlanner, ...],
        missions: MissionController,
        macro_planner: MacroPlanner,
        economy: EconomyController,
        macro_diagnostics: MacroDiagnostics,
        telemetry: FrameTelemetry,
    ) -> None:
        self._logger = logger
        self._world_observer = world_observer
        self._awareness = awareness
        self._vision = vision
        self._services = services
        self._scouting_vision = scouting_vision
        self._mission_planners = mission_planners
        self._missions = missions
        self._macro_planner = macro_planner
        self._economy = economy
        self._macro_diagnostics = macro_diagnostics
        self._telemetry = telemetry

    async def process(self, bot, *, iteration: int) -> None:
        world = self._world_observer.world_facts(bot, iteration=iteration)
        attention = AttentionService.build(world=world)
        awareness = self._awareness.update(attention)
        self._log_belief_changes(awareness)

        await self._step_behavior(bot, attention, awareness)
        self._step_macro(bot, attention, awareness)

        self._telemetry.report(bot, attention, awareness)

    def _log_belief_changes(self, awareness: AwarenessSnapshot) -> None:
        """Log stable economy/army belief changes without exposing them in chat."""

        for message in awareness.belief_changes:
            self._logger.event(
                "awareness.belief_changed",
                component="world.awareness.belief",
                game_time=awareness.updated_at,
                data={"message": message},
            )

    async def _step_behavior(
        self, bot, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> None:
        # Shared capabilities collect needs from every behavior before
        # choosing how to satisfy them once for the frame.
        self._vision.begin_frame(attention, AresVisionCommands(bot))
        self._scouting_vision.tick(attention, awareness)

        # Behavior: units already on the map, owned through missions.
        proposals = tuple(
            proposal
            for planner in self._mission_planners
            for proposal in planner.propose(attention, awareness)
        )
        self._vision.resolve()
        register_baseline_behaviors(bot)
        commands = AresMissionCommands(bot, self._missions.allocator)
        await self._missions.tick(
            attention=attention,
            awareness=awareness,
            proposals=proposals,
            commands=commands,
            services=self._services,
        )

    def _step_macro(
        self, bot, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> None:
        # Macro: what to spend on, admitted against the bank -- no unit, no
        # mission. It runs during the opening too. The build runner keeps
        # executing its own steps (Ares drives that from its own `on_step`);
        # what we owe it is the money for the next ones, which the economy
        # controller withholds as protected. An unfinished opening is a set
        # of commitments, not a freeze on macro.
        economy_result = self._economy.step(
            attention=attention,
            proposals=self._macro_planner.propose(attention, awareness),
            commands=AresEconomyCommands(bot),
        )
        self._macro_diagnostics.report(
            attention, self._macro_planner.last_status, economy_result
        )

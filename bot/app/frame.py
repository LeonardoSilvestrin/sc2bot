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
from bot.strategy import StrategicContext
from bot.world.attention import AttentionService, AttentionSnapshot
from bot.world.awareness import AwarenessService, AwarenessSnapshot

from .debug import SpatialDebugView, SpatialSnapshotExporter
from .mission_ranking import MissionRanker
from .strategy_runtime import StrategyRuntime
from .telemetry import FrameTelemetry


class FrameProcessor:
    """Carries one game frame from Ares state to decisions and commands.

    One read side feeds two domains that never learn about each other:
    behavior planners, whose missions ``MissionController`` admits and runs on
    units, and ``MacroPlanner``, whose purchases ``EconomyController`` admits
    against the bank. Diagnostics read the outcome last. The step order is
    behavior, not presentation -- see ``docs/frame-lifecycle.md``.
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
        spatial_debug: SpatialDebugView,
        spatial_snapshot: SpatialSnapshotExporter | None = None,
        strategy: StrategyRuntime | None = None,
        mission_ranker: MissionRanker | None = None,
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
        self._spatial_debug = spatial_debug
        self._spatial_snapshot = spatial_snapshot
        self._strategy = strategy
        self._mission_ranker = mission_ranker or MissionRanker(logger=logger)

    async def process(self, bot, *, iteration: int) -> None:
        # Every event this frame emits carries its iteration.
        self._logger.begin_frame(iteration)
        try:
            await self._process(bot, iteration=iteration)
        finally:
            self._logger.end_frame()

    async def _process(self, bot, *, iteration: int) -> None:
        world = self._world_observer.world_facts(bot, iteration=iteration)
        attention = AttentionService.build(world=world)
        awareness = self._awareness.update(attention)
        self._log_belief_changes(awareness)
        strategy: StrategicContext | None = None
        if self._strategy is not None:
            awareness = self._strategy.update(awareness)
            strategy = self._strategy.context

        await self._step_behavior(bot, attention, awareness, strategy)
        self._step_macro(bot, attention, awareness)

        if self._spatial_debug.enabled:
            self._spatial_debug.render(bot, awareness)
        if self._spatial_snapshot is not None:
            self._spatial_snapshot.capture(attention, awareness)
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
        self,
        bot,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
        strategy: StrategicContext | None,
    ) -> None:
        # Shared capabilities collect needs from every behavior before
        # choosing how to satisfy them once for the frame.
        self._vision.begin_frame(attention, AresVisionCommands(bot))
        self._scouting_vision.tick(attention, awareness)

        # Behavior: units already on the map, owned through missions.
        # Planners find opportunities; the Mission Policy evaluates all of
        # them on one scale and only viable ones reach the engine.
        candidates = tuple(
            candidate
            for planner in self._mission_planners
            for candidate in planner.propose(attention, awareness, strategy)
        )
        if candidates and self._strategy is not None:
            # The exact context is on record before any decision cites it.
            self._strategy.record_context()
        proposals = self._mission_ranker.rank(candidates, strategy)
        self._vision.resolve()
        register_baseline_behaviors(bot)
        commands = AresMissionCommands(bot, self._missions.allocator)
        await self._missions.tick(
            attention=attention,
            awareness=awareness,
            proposals=proposals,
            commands=commands,
            services=self._services,
            # Every planner that declared work this frame, viable or not: a
            # standing responsibility whose candidate the policy rejected is
            # withdrawn rather than kept at its old priority.
            declared_planners=frozenset(
                candidate.draft.planner for candidate in candidates
            ),
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

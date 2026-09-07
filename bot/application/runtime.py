from __future__ import annotations

from bot.attention.builder import AttentionBuilder
from bot.awareness.models import AwarenessSnapshot
from bot.awareness.service import AwarenessService
from bot.contracts.economy import EconomicFeedback, ResourceBank
from bot.contracts.logging import BotLogger
from bot.economy import (
    EconomyController,
    merge_economic_feedback,
    observe_economic_confirmations,
)
from bot.ego import MissionController
from bot.infrastructure.ares import (
    AresEconomyCommands,
    AresMissionCommands,
    register_baseline_behaviors,
)
from bot.planners import (
    DefensePlanner,
    DefensePlannerConfig,
    HarassPlanner,
    HarassPlannerConfig,
    IntelPlanner,
    IntelPlannerConfig,
    MacroPlanner,
    MacroPlannerConfig,
)


class BotRuntime:
    """Composition root wiring Attention/Awareness into the mission planners."""

    def __init__(
        self,
        *,
        logger: BotLogger,
        intel_config: IntelPlannerConfig | None = None,
        harass_config: HarassPlannerConfig | None = None,
        defense_config: DefensePlannerConfig | None = None,
        macro_config: MacroPlannerConfig | None = None,
    ) -> None:
        self.logger = logger
        self.intel_config = intel_config or IntelPlannerConfig()
        self.harass_config = harass_config or HarassPlannerConfig()
        self.defense_config = defense_config or DefensePlannerConfig()
        self.macro_config = macro_config or MacroPlannerConfig()
        self.attention_builder = AttentionBuilder()
        self.awareness = AwarenessService(
            location_stale_after=self.intel_config.location_stale_after
        )
        self.intel_planner = IntelPlanner(config=self.intel_config)
        self.harass_planner = HarassPlanner(config=self.harass_config)
        self.defense_planner = DefensePlanner(config=self.defense_config)
        self.macro_planner = MacroPlanner(config=self.macro_config)
        self._mission_planners = (
            self.intel_planner,
            self.harass_planner,
            self.defense_planner,
        )
        self.missions = MissionController(logger=logger)
        self.economy = EconomyController(logger=logger)
        self._pending_economic_feedback: tuple[EconomicFeedback, ...] = ()
        self._last_build_signature: tuple | None = None
        self._last_awareness_signature: tuple | None = None
        self._last_snapshot_at: float = -999.0

    async def on_start(self, bot) -> None:
        self.logger.event(
            "game.started",
            component="application.runtime",
            game_time=float(bot.time),
            data={"map": str(bot.game_info.map_name)},
        )

    async def on_step(self, bot, *, iteration: int) -> None:
        world = self.attention_builder.world_facts(bot, iteration=iteration)
        attention = self.attention_builder.build(world=world)
        awareness = self.awareness.update(attention)
        proposals = tuple(
            proposal
            for planner in self._mission_planners
            for proposal in planner.propose(attention, awareness)
        )

        register_baseline_behaviors(bot)
        commands = AresMissionCommands(bot, self.missions.allocator)
        await self.missions.tick(
            attention=attention,
            awareness=awareness,
            proposals=proposals,
            commands=commands,
        )

        runner = getattr(bot, "build_order_runner", None)
        if bool(getattr(runner, "build_completed", False)):
            economic_proposals = self.macro_planner.propose(attention, awareness)
            observed_feedback = observe_economic_confirmations(
                self.economy.snapshots(), world.economy
            )
            feedback = merge_economic_feedback(
                observed_feedback, self._pending_economic_feedback
            )
            bank = ResourceBank(
                minerals=max(0, world.minerals),
                vespene=max(0, world.vespene),
                supply_available=max(0.0, world.supply_cap - world.supply_used),
            )
            result = self.economy.tick(
                now=world.time,
                bank=bank,
                proposals=economic_proposals,
                feedback=feedback,
            )
            economy_commands = AresEconomyCommands(bot)
            self._pending_economic_feedback = tuple(
                economy_commands.dispatch(action)
                for action in result.admitted_actions
            )
        else:
            self._pending_economic_feedback = ()

        self._log_build_order(bot, game_time=world.time)
        self._log_awareness(attention, awareness)

    def _log_build_order(self, bot, *, game_time: float) -> None:
        runner = getattr(bot, "build_order_runner", None)
        if runner is None:
            return
        step = int(getattr(runner, "build_step", 0))
        build_order = tuple(getattr(runner, "build_order", ()) or ())
        completed = bool(getattr(runner, "build_completed", False))
        opening = str(getattr(runner, "chosen_opening", ""))
        command = None
        if not completed and step < len(build_order):
            command = str(getattr(build_order[step], "command", build_order[step]))
        signature = (opening, step, completed, command)
        if signature == self._last_build_signature:
            return
        self._last_build_signature = signature
        self.logger.event(
            "macro.build_order_progress",
            component="application.runtime",
            game_time=game_time,
            data={
                "opening": opening,
                "step": step,
                "total_steps": len(build_order),
                "command": command,
                "completed": completed,
            },
        )

    def _log_awareness(self, attention, awareness: AwarenessSnapshot) -> None:
        world = attention.world
        economy = world.economy
        strength = awareness.relative_strength
        threat = awareness.threat
        live_missions = tuple(
            mission
            for mission in self.missions.snapshots()
            if not mission.status.terminal
        )
        signature = (
            awareness.macro_posture,
            round(strength.score, 3),
            round(strength.confidence, 3),
            strength.own_combat_units,
            strength.known_enemy_combat_units,
            threat.visible_enemy_units,
            threat.known_anti_air_units,
            threat.visible_anti_air_units,
            threat.visible_enemy_combat_units,
            threat.near_own_base_enemy_units,
            threat.near_own_base_enemy_combat_units,
            len(awareness.enemy.sightings),
            tuple(
                (mission.mission_id, mission.status.name) for mission in live_missions
            ),
        )
        changed = signature != self._last_awareness_signature
        periodic = world.time - self._last_snapshot_at >= 10.0
        if not changed and not periodic:
            return
        self._last_awareness_signature = signature
        self._last_snapshot_at = world.time
        self.logger.event(
            "awareness.updated",
            component="application.runtime",
            game_time=world.time,
            data={
                "posture": awareness.macro_posture.name,
                "relative_strength": {
                    "score": round(strength.score, 3),
                    "confidence": round(strength.confidence, 3),
                    "own_combat_units": strength.own_combat_units,
                    "known_enemy_combat_units": strength.known_enemy_combat_units,
                },
                "threat": {
                    "visible_enemy_units": threat.visible_enemy_units,
                    "known_anti_air_units": threat.known_anti_air_units,
                    "visible_anti_air_units": threat.visible_anti_air_units,
                    "visible_enemy_combat_units": (
                        threat.visible_enemy_combat_units
                    ),
                    "near_own_base_enemy_units": (
                        threat.near_own_base_enemy_units
                    ),
                    "near_own_base_enemy_combat_units": (
                        threat.near_own_base_enemy_combat_units
                    ),
                },
                "enemy_sightings": len(awareness.enemy.sightings),
                "active_missions": len(live_missions),
            },
        )
        self.logger.event(
            "attention.world_state",
            component="application.runtime",
            game_time=world.time,
            data={
                "minerals": world.minerals,
                "vespene": world.vespene,
                "supply_used": world.supply_used,
                "supply_cap": world.supply_cap,
                "economy": {
                    "opening_name": economy.opening_name,
                    "opening_completed": economy.opening_completed,
                    "mineral_collection_rate": economy.mineral_collection_rate,
                    "vespene_collection_rate": economy.vespene_collection_rate,
                    "workers": {
                        "existing": economy.workers.existing,
                        "ready": economy.workers.ready,
                        "pending": economy.workers.pending,
                    },
                    "townhalls": {
                        "existing": economy.townhalls.existing,
                        "ready": economy.townhalls.ready,
                        "pending": economy.townhalls.pending,
                    },
                    "ideal_harvesters": economy.ideal_harvesters,
                    "assigned_harvesters": economy.assigned_harvesters,
                    "supply_pending": economy.supply_pending,
                },
                "own_unit_count": len(world.own_units),
                "own_structure_count": len(world.own_structures),
                "visible_enemy_unit_count": sum(
                    unit.visible_now for unit in world.enemy_units
                ),
            },
        )

    async def on_end(self, bot, *, result) -> None:
        self.logger.event(
            "game.ended",
            component="application.runtime",
            game_time=float(bot.time),
            data={"result": str(result)},
        )
        self.logger.close()

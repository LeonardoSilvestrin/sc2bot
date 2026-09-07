from __future__ import annotations

import random

from ares.consts import BUILD_CHOICES, CYCLE, DEBUG, TEST_OPPONENT_ID

from bot.adapters.ares import (
    AresEconomyCommands,
    AresMissionCommands,
    register_baseline_behaviors,
)
from bot.app.mission_registry import DEFAULT_EXECUTOR_FACTORIES
from bot.behavior.defense import DefensePlanner, DefensePlannerConfig
from bot.behavior.harass import (
    BansheeHarassPlanner,
    BansheeHarassPlannerConfig,
    HarassPlanner,
    HarassPlannerConfig,
)
from bot.behavior.macro import (
    MacroPlanner,
    MacroPlannerConfig,
    macro_config_for_opening,
)
from bot.behavior.map_control import MapControlPlanner, MapControlPlannerConfig
from bot.behavior.scouting import IntelPlanner, IntelPlannerConfig
from bot.engine.economy import (
    EconomicFeedback,
    EconomyController,
    ResourceBank,
    merge_economic_feedback,
    observe_economic_confirmations,
)
from bot.engine.missions import MissionController
from bot.ports.logging import BotLogger
from bot.world.knowledge.models import AwarenessSnapshot
from bot.world.knowledge.service import AwarenessService
from bot.world.observation.builder import AttentionBuilder

# `terran_builds.yml` sets `UseData: false` (ladder-safe: never persist
# opponent history to disk), which makes Ares' own build-selection cycle
# always resolve to `Cycle[0]` -- see `DataManager.initialise`. That pinned
# every game to `BioThreeOneOne` and the `BansheeCloak` opener never ran.
# `_choose_and_announce_opening` re-picks from that same cycle ourselves so
# every configured opening actually gets played.
_OPENING_ANNOUNCEMENTS: dict[str, str] = {
    "BioThreeOneOne": "Plan: Reaper expand into Bio 3-1-1.",
    "BansheeCloak": "Plan: Reaper expand into cloaked Banshee harass.",
}


class BotRuntime:
    """Composition root wiring Attention/Awareness into the mission planners."""

    def __init__(
        self,
        *,
        logger: BotLogger,
        intel_config: IntelPlannerConfig | None = None,
        harass_config: HarassPlannerConfig | None = None,
        banshee_harass_config: BansheeHarassPlannerConfig | None = None,
        defense_config: DefensePlannerConfig | None = None,
        macro_config: MacroPlannerConfig | None = None,
        map_control_config: MapControlPlannerConfig | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.logger = logger
        self._rng = rng or random.Random()
        self.intel_config = intel_config or IntelPlannerConfig()
        self.harass_config = harass_config or HarassPlannerConfig()
        self.banshee_harass_config = (
            banshee_harass_config or BansheeHarassPlannerConfig()
        )
        self.defense_config = defense_config or DefensePlannerConfig()
        self.macro_config = macro_config or MacroPlannerConfig()
        self.map_control_config = map_control_config or MapControlPlannerConfig()
        self.attention_builder = AttentionBuilder()
        self.awareness = AwarenessService(
            location_stale_after=self.intel_config.location_stale_after
        )
        self.intel_planner = IntelPlanner(config=self.intel_config)
        self.harass_planner = HarassPlanner(config=self.harass_config)
        self.banshee_harass_planner = BansheeHarassPlanner(
            config=self.banshee_harass_config
        )
        self.defense_planner = DefensePlanner(config=self.defense_config)
        self.macro_planner = MacroPlanner(config=self.macro_config)
        self.map_control_planner = MapControlPlanner(config=self.map_control_config)
        self._mission_planners = (
            self.intel_planner,
            self.harass_planner,
            self.banshee_harass_planner,
            self.defense_planner,
            self.map_control_planner,
        )
        # `chosen_opening` is unknown until the Ares build runner resolves it
        # (never, if a caller pins `macro_config` explicitly, e.g. tests) --
        # see `_resolve_macro_profile`.
        self._macro_profile_resolved = macro_config is not None
        self.missions = MissionController(
            logger=logger,
            executor_factories=DEFAULT_EXECUTOR_FACTORIES,
        )
        self.economy = EconomyController(logger=logger)
        self._pending_economic_feedback: tuple[EconomicFeedback, ...] = ()
        self._last_build_signature: tuple | None = None
        self._last_world_signature: tuple | None = None
        self._last_world_snapshot_at: float = -999.0
        self._last_enemy_intel_signature: tuple | None = None

    async def on_start(self, bot) -> None:
        await self._choose_and_announce_opening(bot)
        self.logger.event(
            "game.started",
            component="app.runtime",
            game_time=float(bot.time),
            data={"map": str(bot.game_info.map_name)},
        )

    async def _choose_and_announce_opening(self, bot) -> None:
        """Pick this game's opening ourselves and declare it in chat.

        Ares' `chosen_opening` is already set by the time `on_start` runs,
        but with `UseData: false` it is always `Cycle[0]` (see the module
        docstring above `_OPENING_ANNOUNCEMENTS`). We re-roll from the same
        configured cycle here, before the build runner has taken a single
        step, so switching is free.
        """

        runner = getattr(bot, "build_order_runner", None)
        if runner is None:
            return
        choices = self._opening_choices(bot, runner)
        if choices:
            switch_opening = getattr(runner, "switch_opening", None)
            if callable(switch_opening):
                switch_opening(self._rng.choice(choices))
        opening = str(getattr(runner, "chosen_opening", "") or "")
        if not opening:
            return
        chat_send = getattr(bot, "chat_send", None)
        if callable(chat_send):
            message = _OPENING_ANNOUNCEMENTS.get(opening, f"Plan: {opening}.")
            await chat_send(message)

    @staticmethod
    def _opening_choices(bot, runner) -> tuple[str, ...]:
        config = getattr(runner, "config", None)
        if not isinstance(config, dict):
            return ()
        build_choices = config.get(BUILD_CHOICES)
        if not build_choices:
            return ()
        opponent_id = (
            TEST_OPPONENT_ID
            if config.get(DEBUG)
            else getattr(bot, "opponent_id", None)
        )
        key = opponent_id if opponent_id in build_choices else None
        if key is None:
            race_name = getattr(getattr(bot, "enemy_race", None), "name", None)
            key = race_name if race_name in build_choices else None
        if key is None:
            return ()
        return tuple(build_choices[key].get(CYCLE, ()) or ())

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
        self._resolve_macro_profile(runner)
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
            self.economy.tick(
                now=world.time,
                bank=bank,
                proposals=economic_proposals,
                feedback=feedback,
            )
            economy_commands = AresEconomyCommands(bot)
            live_actions = tuple(
                snapshot.action
                for snapshot in self.economy.snapshots()
                if not snapshot.status.terminal
            )
            self._pending_economic_feedback = tuple(
                dispatched
                for action in live_actions
                if (dispatched := economy_commands.dispatch(action)) is not None
            )
        else:
            self._pending_economic_feedback = ()

        self._log_build_order(bot, game_time=world.time)
        self._log_world_snapshots(attention, awareness)

    def _resolve_macro_profile(self, runner) -> None:
        """Pick the post-opening `MacroGoalSet` matching the chosen opening.

        The Ares build runner only knows `chosen_opening` once it selects a
        build from `terran_builds.yml`, which is not yet resolved at
        `BotRuntime.__init__`. Resolved once and then locked in: an opening
        does not change mid-game, and re-resolving every frame would just
        rebuild an identical `MacroPlanner` for no reason.
        """

        if self._macro_profile_resolved:
            return
        opening = str(getattr(runner, "chosen_opening", "") or "")
        if not opening:
            return
        self.macro_config = macro_config_for_opening(opening)
        self.macro_planner = MacroPlanner(config=self.macro_config)
        self._macro_profile_resolved = True

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
            component="app.runtime",
            game_time=game_time,
            data={
                "opening": opening,
                "step": step,
                "total_steps": len(build_order),
                "command": command,
                "completed": completed,
            },
        )

    def _log_world_snapshots(self, attention, awareness: AwarenessSnapshot) -> None:
        world = attention.world
        self._log_enemy_intel(awareness, game_time=world.time)
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
        changed = signature != self._last_world_signature
        periodic = world.time - self._last_world_snapshot_at >= 10.0
        if not changed and not periodic:
            return
        self._last_world_signature = signature
        self._last_world_snapshot_at = world.time
        self.logger.event(
            "knowledge.updated",
            component="world.knowledge",
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
            "observation.updated",
            component="world.observation",
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

    def _log_enemy_intel(
        self, awareness: AwarenessSnapshot, *, game_time: float
    ) -> None:
        """Expose scout discoveries without bloating periodic world snapshots."""

        structures = tuple(
            sighting for sighting in awareness.enemy.sightings if sighting.is_structure
        )
        confirmed_locations = tuple(
            location.key
            for location in awareness.enemy.locations
            if location.last_observed_at is not None
        )
        signature = (
            tuple(
                (
                    structure.tag,
                    structure.unit_type,
                    round(structure.last_position.x, 1),
                    round(structure.last_position.y, 1),
                    structure.visible_now,
                )
                for structure in structures
            ),
            confirmed_locations,
        )
        if signature == self._last_enemy_intel_signature:
            return
        self._last_enemy_intel_signature = signature
        self.logger.event(
            "knowledge.enemy_intel",
            component="world.knowledge.enemy",
            game_time=game_time,
            data={
                "known_enemy_bases": awareness.enemy.known_base_count,
                "known_enemy_structures": awareness.enemy.known_structure_count,
                "confirmed_locations": list(confirmed_locations),
                "structures": [
                    {
                        "tag": structure.tag,
                        "type": structure.unit_type.name,
                        "position": [
                            round(float(structure.last_position.x), 1),
                            round(float(structure.last_position.y), 1),
                        ],
                        "visible_now": structure.visible_now,
                        "last_seen_at": structure.last_seen_at,
                    }
                    for structure in structures
                ],
            },
        )

    async def on_end(self, bot, *, result) -> None:
        self.logger.event(
            "game.ended",
            component="app.runtime",
            game_time=float(bot.time),
            data={"result": str(result)},
        )
        self.logger.close()

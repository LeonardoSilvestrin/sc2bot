from __future__ import annotations

import random

from ares.consts import BUILD_CHOICES, CYCLE, DEBUG, TEST_OPPONENT_ID

from bot.adapters.ares import (
    AresEconomyCommands,
    AresMissionCommands,
    AresVisionCommands,
    AresWorldObserver,
    register_baseline_behaviors,
)
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
from bot.domain import is_combat_unit
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
from bot.world.attention import AttentionService
from bot.world.awareness import (
    AwarenessService,
    AwarenessSnapshot,
    SpatialModelConfig,
)

# `terran_builds.yml` sets `UseData: false` (ladder-safe: never persist
# opponent history to disk), which makes Ares' own build-selection cycle
# always resolve to `Cycle[0]` -- see `DataManager.initialise`. That pinned
# every game to `BioThreeOneOne` and the `BansheeCloak` opener never ran.
# `_choose_and_announce_opening` re-picks from that same cycle ourselves so
# every configured opening actually gets played.
_OPENING_ANNOUNCEMENTS: dict[str, str] = {
    "BioThreeOneOne": "Reaper expand into Bio 3-1-1.",
    "BansheeCloak": "Reaper expand into cloaked Banshee harass.",
    "BattleMech": "get ready baby",
}


class BotRuntime:
    """Composition root: one read side, two domains.

    Attention and Awareness feed the behavior planners, whose missions
    `MissionController` admits and runs on units, and `MacroPlanner`, whose
    purchases `EconomyController` admits against the bank and dispatches.
    Neither domain knows the other exists; this class only wires them.
    """

    # How long an eligible combat unit may sit without any mission owning it
    # before it is worth a distinct log line -- the standing behavior is the
    # default owner, so this should not normally happen at all.
    _UNASSIGNED_WARNING_AFTER = 15.0

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
        rng: random.Random | None = None,
    ) -> None:
        self.logger = logger
        self._rng = rng or random.Random()
        self.intel_config = intel_config or IntelConfig()
        self.scouting_vision_config = (
            scouting_vision_config or ScoutingVisionConfig()
        )
        self.banshee_harass_config = banshee_harass_config or BansheeHarassConfig()
        self.reaper_harass_config = reaper_harass_config or ReaperHarassConfig()
        self.defense_config = defense_config or DefenseConfig()
        self.map_control_config = map_control_config or MapControlConfig()
        self.standing_config = standing_config or StandingConfig()
        self.world_observer = AresWorldObserver(
            spatial_sample_spacing=spatial_sample_spacing
        )
        self.awareness = AwarenessService(
            location_stale_after=self.intel_config.location_stale_after,
            spatial_model_config=spatial_model_config,
            logger=logger,
        )
        self.vision = VisionService(
            provider=ScanProvider(
                config=scan_provider_config or ScanProviderConfig(), logger=logger
            ),
            config=vision_service_config or VisionServiceConfig(),
            logger=logger,
        )
        self.services = BehaviorServices(vision=self.vision)
        # Behavior domain: planners propose missions for units on the map.
        self.intel_planner = IntelPlanner(config=self.intel_config, logger=logger)
        self.scouting_vision = ScoutingVisionRequester(
            services=self.services,
            config=self.scouting_vision_config,
            logger=logger,
        )
        self.banshee_harass_planner = BansheeHarassPlanner(
            config=self.banshee_harass_config, logger=logger
        )
        self.reaper_harass_planner = ReaperHarassPlanner(
            config=self.reaper_harass_config, logger=logger
        )
        self.defense_planner = DefensePlanner(
            config=self.defense_config,
            logger=logger,
            services=self.services,
        )
        self.map_control_planner = MapControlPlanner(
            config=self.map_control_config, logger=logger
        )
        self.standing_planner = StandingPlanner(
            config=self.standing_config, logger=logger
        )
        self._mission_planners = (
            self.intel_planner,
            self.reaper_harass_planner,
            self.banshee_harass_planner,
            self.defense_planner,
            self.map_control_planner,
            # The default behavior last: its standing proposal should not
            # shadow anything above in reasoning about this tick's proposal
            # list, though admission order does not actually depend on list
            # order (MissionController sorts live missions by priority every
            # tick regardless).
            self.standing_planner,
        )
        self.missions = MissionController(
            logger=logger,
            executor_factories=build_executor_factories(
                standing_config=self.standing_config,
                banshee_config=self.banshee_harass_config,
                reaper_config=self.reaper_harass_config,
                defense_config=self.defense_config,
                map_control_config=self.map_control_config,
                intel_config=self.intel_config,
                logger=logger,
            ),
        )
        # Macro domain: what to spend on, admitted against the bank. The
        # opening is unknown until the Ares build runner resolves it, so the
        # planner follows it -- unless a caller pins `macro_config` (tests).
        self.macro_planner = MacroPlanner(
            config=macro_config or MacroPlannerConfig(),
            follow_opening=macro_config is None,
        )
        self.economy = EconomyController(logger=logger)
        self.macro_diagnostics = MacroDiagnostics(logger=logger)
        self._last_build_signature: tuple | None = None
        self._last_world_signature: tuple | None = None
        self._last_world_snapshot_at: float = -999.0
        self._last_enemy_intel_signature: tuple | None = None
        self._last_enemy_model_signature: tuple | None = None
        self._last_enemy_model_log_at: float = -999.0
        self._last_belief_signature: tuple | None = None
        self._last_belief_log_at: float = -999.0
        self._last_standing_signature: tuple | None = None
        self._last_standing_log_at: float = -999.0
        self._unassigned_eligible_since: float | None = None

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
            description = _OPENING_ANNOUNCEMENTS.get(opening)
            message = f"[Build] {opening}"
            if description:
                message += f" - {description}"
            await chat_send(message)

    async def _announce_awareness_changes(
        self, bot, awareness: AwarenessSnapshot
    ) -> None:
        """Speak a stable economy/army belief change in game chat.

        ``AwarenessService`` decides *whether* a change happened (and
        debounces it against flapping) -- this only performs the I/O, same
        division as ``_choose_and_announce_opening``.
        """

        if not awareness.chat_messages:
            return
        chat_send = getattr(bot, "chat_send", None)
        for message in awareness.chat_messages:
            self.logger.event(
                "awareness.belief_changed",
                component="world.awareness.belief",
                game_time=awareness.updated_at,
                data={"message": message},
            )
            if callable(chat_send):
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
        world = self.world_observer.world_facts(bot, iteration=iteration)
        attention = AttentionService.build(world=world)
        awareness = self.awareness.update(attention)
        await self._announce_awareness_changes(bot, awareness)

        # Shared capabilities collect needs from every behavior before
        # choosing how to satisfy them once for the frame.
        self.vision.begin_frame(attention, AresVisionCommands(bot))
        self.scouting_vision.tick(attention, awareness)

        # Behavior: units already on the map, owned through missions.
        proposals = tuple(
            proposal
            for planner in self._mission_planners
            for proposal in planner.propose(attention, awareness)
        )
        self.vision.resolve()
        register_baseline_behaviors(bot)
        commands = AresMissionCommands(bot, self.missions.allocator)
        await self.missions.tick(
            attention=attention,
            awareness=awareness,
            proposals=proposals,
            commands=commands,
            services=self.services,
        )

        # Macro: what to spend on, admitted against the bank -- no unit, no
        # mission. It runs during the opening too. The build runner keeps
        # executing its own steps (Ares drives that from its own `on_step`);
        # what we owe it is the money for the next ones, which the economy
        # controller withholds as protected. An unfinished opening is a set
        # of commitments, not a freeze on macro.
        economy_result = self.economy.step(
            attention=attention,
            proposals=self.macro_planner.propose(attention, awareness),
            commands=AresEconomyCommands(bot),
        )
        self.macro_diagnostics.report(
            attention, self.macro_planner.last_status, economy_result
        )

        self._log_build_order(bot, game_time=world.time)
        self._log_world_snapshots(attention, awareness)
        self._log_standing(attention)

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
        self._log_enemy_model(awareness, game_time=world.time)
        self._log_world_belief(awareness, game_time=world.time)
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
            component="world.awareness",
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
            component="world.attention",
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

    def _log_world_belief(
        self, awareness: AwarenessSnapshot, *, game_time: float
    ) -> None:
        """Dump the full economy/army belief, including *why it has not
        changed yet* (raw vs stable, confidence) -- not just the final
        stable state, which the chat announcements already cover."""

        economy = awareness.economy
        army = awareness.army
        signature = (
            economy.relative.raw_state,
            economy.relative.stable_state,
            army.relative.raw_state,
            army.relative.stable_state,
        )
        changed = signature != self._last_belief_signature
        periodic = game_time - self._last_belief_log_at >= 10.0
        if not changed and not periodic:
            return
        self._last_belief_signature = signature
        self._last_belief_log_at = game_time
        self.logger.event(
            "awareness.world_belief",
            component="world.awareness.belief",
            game_time=game_time,
            data={
                "economy": {
                    "own_workers": economy.own_workers,
                    "own_bases": economy.own_bases,
                    "enemy_observed_workers": economy.enemy.workers.observed,
                    "enemy_known_workers": round(economy.enemy.workers.known, 1),
                    "enemy_estimated_workers": economy.enemy.workers.estimated,
                    "enemy_workers_uncertainty": round(
                        economy.enemy.workers.uncertainty, 1
                    ),
                    "enemy_confirmed_bases": economy.enemy.bases.confirmed,
                    "enemy_estimated_bases": economy.enemy.bases.estimated,
                    "raw": economy.relative.raw_state.name,
                    "stable": economy.relative.stable_state.name,
                    "advantage": round(economy.relative.advantage, 3),
                    "confidence": round(economy.relative.confidence, 3),
                },
                "army": {
                    "own_supply": round(army.own_supply, 1),
                    "enemy_observed_supply": round(army.enemy.supply.observed, 1),
                    "enemy_known_supply": round(army.enemy.supply.known, 1),
                    "enemy_estimated_supply": round(army.enemy.supply.estimated, 1),
                    "enemy_supply_uncertainty": round(
                        army.enemy.supply.uncertainty, 1
                    ),
                    "raw": army.relative.raw_state.name,
                    "stable": army.relative.stable_state.name,
                    "advantage": round(army.relative.advantage, 3),
                    "confidence": round(army.relative.confidence, 3),
                },
            },
        )

    def _log_standing(self, attention) -> None:
        """Surface standing-army ownership so "why is this unit here?" and
        "how many units have no mission?" are answerable from the logs.

        Grouped by ``deduplication_key``/``kind`` straight off the live
        ``Mission`` objects (not ``MissionSnapshot``, which drops
        ``requirement.desired``) -- this is diagnostics, not a second source
        of truth: ownership itself still lives only in ``UnitAllocator``.
        """

        world = attention.world
        standing: dict[str, tuple[int, int]] = {}
        allocation_by_kind: dict[str, int] = {}
        for mission in self.missions.board.live():
            kind_name = mission.proposal.kind.name
            allocation_by_kind[kind_name] = allocation_by_kind.get(
                kind_name, 0
            ) + len(mission.assigned_unit_tags)
            if mission.proposal.squad_id is not None:
                slot = mission.proposal.squad_id
                standing[slot] = (
                    mission.proposal.requirement.desired,
                    len(mission.assigned_unit_tags),
                )

        unassigned_tags = tuple(
            unit.tag
            for unit in world.own_units
            if is_combat_unit(unit.unit_type)
            and unit.available_for_mission
            and self.missions.allocator.owner_of(unit.tag) is None
        )

        if unassigned_tags:
            if self._unassigned_eligible_since is None:
                self._unassigned_eligible_since = world.time
        else:
            self._unassigned_eligible_since = None
        unassigned_duration = (
            0.0
            if self._unassigned_eligible_since is None
            else world.time - self._unassigned_eligible_since
        )

        signature = (
            self.standing_planner.last_posture.name,
            tuple(sorted(standing.items())),
            tuple(sorted(allocation_by_kind.items())),
            len(unassigned_tags),
        )
        periodic = world.time - self._last_standing_log_at >= 10.0
        if signature == self._last_standing_signature and not periodic:
            return
        self._last_standing_signature = signature
        self._last_standing_log_at = world.time

        self.logger.event(
            "standing.updated",
            component="behavior.standing",
            game_time=world.time,
            data={
                "combat_posture": self.standing_planner.last_posture.name,
                "standing": {
                    slot: {"desired": desired, "assigned": assigned}
                    for slot, (desired, assigned) in sorted(standing.items())
                },
                "mission_allocation": allocation_by_kind,
                "squads": [
                    {
                        "squad_id": squad.squad_id,
                        "role": squad.role.name,
                        "members": list(squad.member_tags),
                        "current_mission_id": squad.current_mission_id,
                        "home_mission_id": squad.home_mission_id,
                    }
                    for squad in self.missions.squads.snapshots()
                ],
                "unassigned_eligible_units": len(unassigned_tags),
            },
        )

        if unassigned_tags and unassigned_duration >= self._UNASSIGNED_WARNING_AFTER:
            self.logger.event(
                "standing.unassigned_units_persisting",
                component="behavior.standing",
                game_time=world.time,
                data={
                    "unassigned_eligible_units": len(unassigned_tags),
                    "unassigned_unit_tags": list(unassigned_tags),
                    "duration_seconds": round(unassigned_duration, 1),
                },
            )

    def _log_enemy_model(
        self, awareness: AwarenessSnapshot, *, game_time: float
    ) -> None:
        """Log where the enemy's bases and forces are believed to be.

        Freshness moves every number every frame, so only a change in which
        bases are confirmed or which cluster is the main force logs at once;
        the numbers otherwise ride a ten-second heartbeat.
        """

        enemy = awareness.enemy
        confirmed = enemy.bases.confirmed
        main_force = enemy.main_force
        main_force_id = None if main_force is None else main_force.cluster_id
        signature = (tuple(base.key for base in confirmed), main_force_id)
        changed = signature != self._last_enemy_model_signature
        periodic = game_time - self._last_enemy_model_log_at >= 10.0
        if not changed and not periodic:
            return
        self._last_enemy_model_signature = signature
        self._last_enemy_model_log_at = game_time
        self.logger.event(
            "knowledge.enemy_model",
            component="world.awareness.enemy",
            game_time=game_time,
            data={
                "bases": [
                    {
                        "key": base.key,
                        "economic_value": round(base.economic_value, 2),
                        "workers": base.worker_count_estimate,
                        "air_defense": round(base.air_defense, 2),
                        "air_defense_confidence": round(
                            base.air_defense_confidence, 2
                        ),
                        "ground_defense": round(base.ground_defense, 2),
                        "ground_defense_confidence": round(
                            base.ground_defense_confidence, 2
                        ),
                        "confidence": round(base.confidence, 2),
                    }
                    for base in confirmed
                ],
                "forces": [
                    {
                        "cluster_id": cluster.cluster_id,
                        "center": [
                            round(float(cluster.center.x), 1),
                            round(float(cluster.center.y), 1),
                        ],
                        "radius": round(cluster.radius, 1),
                        "position_uncertainty": round(
                            cluster.position_uncertainty, 1
                        ),
                        "strength": round(cluster.combat_strength, 1),
                        "anti_air": round(cluster.anti_air_strength, 1),
                        "anti_ground": round(cluster.anti_ground_strength, 1),
                        "units": cluster.unit_count,
                        "visible_units": cluster.visible_unit_count,
                        "confidence": round(cluster.confidence, 2),
                    }
                    for cluster in enemy.forces
                ],
                "main_force": main_force_id,
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
            component="world.awareness.enemy",
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

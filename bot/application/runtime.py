from __future__ import annotations

from bot.actions.scheduler import ActionScheduler
from bot.attention.builder import AttentionBuilder
from bot.awareness.service import AwarenessService
from bot.contracts.logging import BotLogger
from bot.infrastructure.ares.commands import AresActionCommands
from bot.knowledge import EnemyKnowledge
from bot.units.registry import UnitRegistry


class BotRuntime:
    """Composition root for the pilot architecture."""

    def __init__(self, *, logger: BotLogger) -> None:
        self.logger = logger
        self.attention_builder = AttentionBuilder()
        self.awareness = AwarenessService()
        self.enemy_knowledge = EnemyKnowledge()
        self.units = UnitRegistry()
        self.actions = ActionScheduler(registry=self.units, logger=logger)
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
        enemy_knowledge = self.enemy_knowledge.update(world)
        awareness = self.awareness.update(world, enemy_knowledge)
        attention = self.attention_builder.build(
            world=world,
            enemy_knowledge=enemy_knowledge,
            awareness=awareness,
            missions=self.actions.mission_summaries(),
        )
        self._log_build_order(bot, game_time=world.time)
        self._log_awareness(attention)
        commands = AresActionCommands(bot, self.units)
        await self.actions.tick(attention, commands=commands)

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

    def _log_awareness(self, attention) -> None:
        strength = attention.awareness.relative_strength
        threat = attention.awareness.threat
        signature = (
            strength.own_combat_units,
            strength.known_enemy_combat_units,
            threat.visible_enemy_units,
            threat.known_anti_air_units,
            len(attention.enemy_knowledge.sightings),
        )
        changed = signature != self._last_awareness_signature
        periodic = attention.world.time - self._last_snapshot_at >= 10.0
        if not changed and not periodic:
            return
        self._last_awareness_signature = signature
        self._last_snapshot_at = attention.world.time
        self.logger.event(
            "attention.snapshot",
            component="application.runtime",
            game_time=attention.world.time,
            data={
                "minerals": attention.world.minerals,
                "vespene": attention.world.vespene,
                "supply": [attention.world.supply_used, attention.world.supply_cap],
                "own_combat_units": strength.own_combat_units,
                "known_enemy_combat_units": strength.known_enemy_combat_units,
                "strength_score": round(strength.score, 3),
                "strength_confidence": round(strength.confidence, 3),
                "visible_enemies": threat.visible_enemy_units,
                "known_anti_air": threat.known_anti_air_units,
                "active_missions": len(attention.missions),
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

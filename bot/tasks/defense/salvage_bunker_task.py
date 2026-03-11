from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.mind.attention import Attention
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class SalvageBunkerTask(BaseTask):
    bunker_tag: int
    bunker_pos: Point2

    def __init__(self, *, bunker_tag: int, bunker_pos: Point2) -> None:
        super().__init__(task_id="salvage_bunker", domain="DEFENSE", commitment=20)
        self.bunker_tag = int(bunker_tag)
        self.bunker_pos = bunker_pos

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound()
        if bound_err is not None:
            return bound_err

        try:
            bunker = bot.structures.find_by_tag(int(self.bunker_tag))
        except Exception:
            bunker = None

        if bunker is None:
            # Bunker gone (destroyed or already salvaged).
            self._done("bunker_gone")
            return TaskResult.done("bunker_gone")

        # Abort if enemies get close before salvage completes.
        try:
            enemies_near = int(bot.enemy_units.closer_than(16.0, bunker.position).amount)
        except Exception:
            enemies_near = 0
        if enemies_near > 0:
            self._done("enemies_near_abort")
            return TaskResult.done("enemies_near_abort")

        # Abort if garrison loaded (bot decided to use bunker after all).
        garrison = int(getattr(bunker, "cargo_used", 0) or 0)
        if garrison > 0:
            self._done("bunker_occupied_abort")
            return TaskResult.done("bunker_occupied_abort")

        try:
            bunker(AbilityId.EFFECT_SALVAGE)
        except Exception:
            self._done("salvage_command_failed")
            return TaskResult.done("salvage_command_failed")

        # Salvage is near-instant; done after issuing the command.
        self._done("salvage_issued")
        return TaskResult.done("salvage_issued")

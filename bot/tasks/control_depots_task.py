# bot/tasks/control_depots_task.py
from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskTick, TaskResult


@dataclass
class ControlDepots(BaseTask):
    """
    Global wall-depot control with no unit leases.
    Raises on nearby threat, lowers otherwise.
    """

    awareness: Awareness

    def __init__(self, *, awareness: Awareness):
        super().__init__(task_id="control_depots", domain="MACRO_DEPOT_CONTROL", commitment=0)
        self.awareness = awareness

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        now = float(tick.time)
        threatened = bool(attention.combat.threatened) and bool(attention.combat.threat_pos)

        issued = 0
        action = "none"

        if threatened:
            lowered = bot.structures.of_type({U.SUPPLYDEPOTLOWERED}).ready
            for depot in lowered:
                depot(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                issued += 1
            action = "raise"
        else:
            raised = bot.structures.of_type({U.SUPPLYDEPOT}).ready
            for depot in raised:
                depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
                issued += 1
            action = "lower"

        self.awareness.mem.set(K("macro", "wall", "depot_control", "last_done_at"), value=now, now=now, ttl=None)
        self.awareness.mem.set(K("macro", "wall", "depot_control", "last_action"), value=action, now=now, ttl=None)

        self._done("depots_controlled")
        return TaskResult.done(
            "depots_controlled",
            telemetry={
                "threatened": bool(threatened),
                "action": str(action),
                "orders": int(issued),
            },
        )

from __future__ import annotations

from dataclasses import dataclass

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class SupportMission(BaseTask):
    """
    Anchor task for reinforcement proposals.
    Reinforcement proposals are admitted into an existing mission by Ego, so this task
    is normally not executed. It remains as a valid TaskSpec factory target.
    """

    awareness: Awareness
    target_mission_id: str

    def __init__(self, *, awareness: Awareness, target_mission_id: str):
        super().__init__(task_id="support_mission", domain="SUPPORT", commitment=1)
        self.awareness = awareness
        self.target_mission_id = str(target_mission_id)

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        now = float(tick.time)
        self.awareness.mem.set(
            K("ops", "mission", self.target_mission_id, "last_support_task_at"),
            value=now,
            now=now,
            ttl=None,
        )
        self._done("support_anchor_done")
        return TaskResult.done("support_anchor_done")

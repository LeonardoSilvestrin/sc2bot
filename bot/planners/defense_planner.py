# bot/planners/defense_planner.py
from __future__ import annotations

from dataclasses import dataclass

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.planners.proposals import Proposal, TaskSpec
from bot.tasks.defend_task import Defend


@dataclass
class DefensePlanner:
    """
    Planner reativo de defesa.
    """
    planner_id: str = "defense_planner"
    defend_task: Defend = None  # template instance

    def _pid_defend(self) -> str:
        return f"{self.planner_id}:defend:bases"

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        if (not bool(attention.combat.threatened)) or (not attention.combat.threat_pos):
            return []

        urg = int(attention.combat.defense_urgency)
        score = max(80, min(100, 60 + urg))

        if self.defend_task is None:
            raise TypeError("DefensePlanner requires defend_task template instance")

        def _factory(mission_id: str) -> Defend:
            return self.defend_task.spawn()

        return [
            Proposal(
                proposal_id=self._pid_defend(),
                domain="DEFENSE",
                score=score,
                tasks=[TaskSpec(task_id="defend_bases", task_factory=_factory, unit_requirements=[])],
                lease_ttl=6.0,
                cooldown_s=0.0,
                risk_level=0,
                allow_preempt=True,
            )
        ]
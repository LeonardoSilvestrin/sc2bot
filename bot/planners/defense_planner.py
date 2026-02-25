from __future__ import annotations

from dataclasses import dataclass

from bot.planners.proposals import Proposal
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.tasks.defend import Defend


@dataclass
class DefensePlanner:
    planner_id: str = "defense_planner"

    def __init__(self, *, awareness: Awareness, defend_task: Defend):
        self.awareness = awareness
        self.defend_task = defend_task

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        if not attention.threatened or not attention.threat_pos:
            return []

        score = 50 + int(attention.defense_urgency)

        return [
            Proposal(
                domain="DEFENSE",
                score=score,
                task=self.defend_task,
                reason="base_threatened",
            )
        ]
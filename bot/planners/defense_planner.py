# bot/planners/defense_planner.py
from __future__ import annotations

from dataclasses import dataclass

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.planners.utils.base_planner import BasePlanner
from bot.planners.utils.proposals import Proposal, TaskSpec
from bot.tasks.defense.defend_task import Defend


@dataclass
class DefensePlanner(BasePlanner):
    """
    Planner reativo de defesa.
    """
    planner_id: str = "defense_planner"
    defend_task: Defend = None  # template instance
    log: DevLogger | None = None

    def _pid_defend(self) -> str:
        return self.proposal_id("defend:bases")

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        if int(attention.combat.primary_urgency) <= 0:
            return []

        now = float(attention.time)
        pid = self._pid_defend()

        # Avoid planner/log spam while an equal DEFENSE mission is already running.
        if self.is_proposal_running(awareness=awareness, proposal_id=pid, now=now):
            return []

        urg = int(attention.combat.primary_urgency)
        score = max(80, min(100, 60 + urg))

        if self.defend_task is None:
            raise TypeError("DefensePlanner requires defend_task template instance")

        def _factory(mission_id: str) -> Defend:
            return self.defend_task.spawn()

        out = self.make_single_task_proposal(
            proposal_id=pid,
            domain="DEFENSE",
            score=score,
            task_spec=TaskSpec(task_id="defend_bases", task_factory=_factory, unit_requirements=[]),
            lease_ttl=6.0,
            cooldown_s=0.0,
            risk_level=0,
            allow_preempt=True,
        )
        self.emit_planner_proposed({"count": len(out), "score": int(score)})
        return out


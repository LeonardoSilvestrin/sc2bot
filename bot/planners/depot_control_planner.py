# bot/planners/depot_control_planner.py
from __future__ import annotations

from dataclasses import dataclass

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.utils.base_planner import BasePlanner
from bot.planners.utils.proposals import Proposal, TaskSpec
from bot.tasks.support.control_depots_task import ControlDepots


@dataclass
class DepotControlPlanner(BasePlanner):
    """
    Periodic proposer for wall-depot control.
    """

    planner_id: str = "depot_control_planner"
    interval_s: float = 1.5
    cooldown_s: float = 0.0
    score: int = 24
    raise_radius: float = 12.0
    raise_urgency_min: int = 18
    raise_enemy_count_min: int = 2
    log: DevLogger | None = None

    def _pid(self) -> str:
        return self.proposal_id("control_depots")

    def _due(self, *, awareness: Awareness, now: float) -> bool:
        return self.due_by_last_done(
            awareness=awareness,
            key=K("macro", "wall", "depot_control", "last_done_at"),
            now=now,
            interval_s=float(self.interval_s),
        )

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)
        pid = self._pid()

        if not self._due(awareness=awareness, now=now):
            return []
        if self.is_proposal_running(awareness=awareness, proposal_id=pid, now=now):
            return []

        threat_pos = attention.combat.primary_threat_pos
        urgency = int(attention.combat.primary_urgency)
        enemy_count = int(attention.combat.primary_enemy_count)
        score = int(self.score) + min(30, max(0, urgency // 2))

        def _factory(mission_id: str) -> ControlDepots:
            return ControlDepots(
                awareness=awareness,
                threat_pos=threat_pos,
                raise_radius=float(self.raise_radius),
                raise_urgency_min=int(self.raise_urgency_min),
                raise_enemy_count_min=int(self.raise_enemy_count_min),
            )

        out = self.make_single_task_proposal(
            proposal_id=pid,
            domain="MACRO_DEPOT_CONTROL",
            score=int(score),
            task_spec=TaskSpec(task_id="control_depots", task_factory=_factory, unit_requirements=[]),
            lease_ttl=None,
            cooldown_s=float(self.cooldown_s),
            risk_level=0,
            allow_preempt=True,
        )

        self.emit_planner_proposed(
            {
                "count": len(out),
                "urgency": int(urgency),
                "enemy_count": int(enemy_count),
                "radius": float(self.raise_radius),
                "raise_urgency_min": int(self.raise_urgency_min),
                "raise_enemy_count_min": int(self.raise_enemy_count_min),
                "has_threat_pos": bool(threat_pos is not None),
            }
        )

        return out


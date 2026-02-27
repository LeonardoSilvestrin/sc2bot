# bot/planners/depot_control_planner.py
from __future__ import annotations

from dataclasses import dataclass

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.proposals import Proposal, TaskSpec
from bot.tasks.control_depots_task import ControlDepots


@dataclass
class DepotControlPlanner:
    """
    Periodic proposer for wall-depot control.
    """

    planner_id: str = "depot_control_planner"
    interval_s: float = 1.5
    cooldown_s: float = 0.0
    score: int = 24
    log: DevLogger | None = None

    def _pid(self) -> str:
        return f"{self.planner_id}:control_depots"

    def _due(self, *, awareness: Awareness, now: float) -> bool:
        last = awareness.mem.get(K("macro", "wall", "depot_control", "last_done_at"), now=now, default=None)
        if last is None:
            return True
        try:
            return (float(now) - float(last)) >= float(self.interval_s)
        except Exception:
            return True

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)
        pid = self._pid()

        if not self._due(awareness=awareness, now=now):
            return []
        if awareness.ops_proposal_running(proposal_id=pid, now=now):
            return []

        def _factory(mission_id: str) -> ControlDepots:
            return ControlDepots(awareness=awareness)

        out = [
            Proposal(
                proposal_id=pid,
                domain="MACRO_DEPOT_CONTROL",
                score=int(self.score),
                tasks=[TaskSpec(task_id="control_depots", task_factory=_factory, unit_requirements=[])],
                lease_ttl=None,
                cooldown_s=float(self.cooldown_s),
                risk_level=0,
                allow_preempt=True,
            )
        ]

        if self.log is not None:
            self.log.emit(
                "planner_proposed",
                {"planner": self.planner_id, "count": len(out)},
                meta={"module": "planner", "component": f"planner.{self.planner_id}"},
            )

        return out

# =============================================================================
# bot/planners/production_planner.py  (NEW)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.planners.proposals import Proposal, TaskSpec
from bot.tasks.macro.production_tick import MacroProductionTick


@dataclass
class ProductionPlanner:
    """
    Always-on production loop (singleton by domain).
    Runs only after opening is done (BuildRunner/yml done).
    """
    planner_id: str = "production_planner"
    score: int = 55
    log: DevLogger | None = None

    scv_cap: int = 66
    log_every_iters: int = 22

    def _pid(self) -> str:
        return f"{self.planner_id}:macro_production"

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)

        # Respect your current opening gate: don't run production loop until opening_done.
        if not bool(attention.macro.opening_done):
            return []

        pid = self._pid()
        if awareness.ops_proposal_running(proposal_id=pid, now=now):
            return []

        def _factory(mission_id: str) -> MacroProductionTick:
            return MacroProductionTick(awareness=awareness, log=self.log, scv_cap=int(self.scv_cap), log_every_iters=int(self.log_every_iters))

        out = [
            Proposal(
                proposal_id=pid,
                domain="MACRO_PRODUCTION",
                score=int(self.score),
                tasks=[TaskSpec(task_id="macro_production", task_factory=_factory, unit_requirements=[])],
                lease_ttl=None,
                cooldown_s=0.0,
                risk_level=0,
                allow_preempt=True,
            )
        ]

        if self.log is not None:
            self.log.emit(
                "planner_proposed",
                {"planner": self.planner_id, "count": len(out), "mode": "production"},
                meta={"module": "planner", "component": f"planner.{self.planner_id}"},
            )
        return out

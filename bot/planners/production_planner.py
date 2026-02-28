# =============================================================================
# bot/planners/production_planner.py  (NEW)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.planners.utils.base_planner import BasePlanner
from bot.planners.utils.proposals import Proposal, TaskSpec
from bot.tasks.macro.production_tick import MacroProductionTick


@dataclass
class ProductionPlanner(BasePlanner):
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
        return self.proposal_id("macro_production")

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)

        # Respect your current opening gate: don't run production loop until opening_done.
        if not bool(attention.macro.opening_done):
            return []

        pid = self._pid()
        if self.is_proposal_running(awareness=awareness, proposal_id=pid, now=now):
            return []

        def _factory(mission_id: str) -> MacroProductionTick:
            return MacroProductionTick(awareness=awareness, log=self.log, scv_cap=int(self.scv_cap), log_every_iters=int(self.log_every_iters))

        out = self.make_single_task_proposal(
            proposal_id=pid,
            domain="MACRO_PRODUCTION",
            score=int(self.score),
            task_spec=TaskSpec(task_id="macro_production", task_factory=_factory, unit_requirements=[]),
            lease_ttl=None,
            cooldown_s=0.0,
            risk_level=0,
            allow_preempt=True,
        )

        self.emit_planner_proposed({"count": len(out), "mode": "production"})
        return out


# =============================================================================
# bot/planners/spending_planner.py  (NEW)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.planners.proposals import Proposal, TaskSpec
from bot.tasks.macro.spending_tick import MacroSpendingTick


@dataclass
class SpendingPlanner:
    """
    Structural spending loop (singleton by domain).
    Runs only after opening is done.
    """
    planner_id: str = "spending_planner"
    score: int = 45
    log: DevLogger | None = None

    target_bases_default: int = 2
    flood_m: int = 800
    flood_hi_m: int = 1400
    flood_hold_s: float = 12.0

    log_every_iters: int = 22

    def _pid(self) -> str:
        return f"{self.planner_id}:macro_spending"

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)

        if not bool(attention.macro.opening_done):
            return []

        pid = self._pid()
        if awareness.ops_proposal_running(proposal_id=pid, now=now):
            return []

        def _factory(mission_id: str) -> MacroSpendingTick:
            return MacroSpendingTick(
                awareness=awareness,
                log=self.log,
                target_bases_default=int(self.target_bases_default),
                flood_m=int(self.flood_m),
                flood_hi_m=int(self.flood_hi_m),
                flood_hold_s=float(self.flood_hold_s),
                log_every_iters=int(self.log_every_iters),
            )

        out = [
            Proposal(
                proposal_id=pid,
                domain="MACRO_SPENDING",
                score=int(self.score),
                tasks=[TaskSpec(task_id="macro_spending", task_factory=_factory, unit_requirements=[])],
                lease_ttl=None,
                cooldown_s=0.0,
                risk_level=0,
                allow_preempt=True,
            )
        ]

        if self.log is not None:
            self.log.emit(
                "planner_proposed",
                {"planner": self.planner_id, "count": len(out), "mode": "spending"},
                meta={"module": "planner", "component": f"planner.{self.planner_id}"},
            )
        return out

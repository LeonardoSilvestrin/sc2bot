# =============================================================================
# bot/planners/spending_planner.py  (NEW)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.planners.utils.base_planner import BasePlanner
from bot.planners.utils.proposals import Proposal, TaskSpec
from bot.tasks.macro.spending_tick import MacroSpendingTick


@dataclass
class SpendingPlanner(BasePlanner):
    """
    Structural spending loop (singleton by domain).
    Runs continuously, including during opening/build-order execution.
    This avoids macro deadlocks when opening stalls.
    """
    planner_id: str = "spending_planner"
    score: int = 45
    log: DevLogger | None = None

    target_bases_default: int = 2
    flood_m: int = 800
    flood_hi_m: int = 1400
    flood_hold_s: float = 12.0
    third_t_normal_s: float = 210.0
    fourth_t_normal_s: float = 330.0
    fifth_t_normal_s: float = 500.0
    third_t_rush_s: float = 290.0
    fourth_t_rush_s: float = 430.0
    fifth_t_rush_s: float = 620.0
    schedule_on_time_window_s: float = 20.0

    log_every_iters: int = 22

    def _pid(self) -> str:
        return self.proposal_id("macro_spending")

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)

        pid = self._pid()
        if self.is_proposal_running(awareness=awareness, proposal_id=pid, now=now):
            return []

        def _factory(mission_id: str) -> MacroSpendingTick:
            return MacroSpendingTick(
                awareness=awareness,
                log=self.log,
                target_bases_default=int(self.target_bases_default),
                flood_m=int(self.flood_m),
                flood_hi_m=int(self.flood_hi_m),
                flood_hold_s=float(self.flood_hold_s),
                third_t_normal_s=float(self.third_t_normal_s),
                fourth_t_normal_s=float(self.fourth_t_normal_s),
                fifth_t_normal_s=float(self.fifth_t_normal_s),
                third_t_rush_s=float(self.third_t_rush_s),
                fourth_t_rush_s=float(self.fourth_t_rush_s),
                fifth_t_rush_s=float(self.fifth_t_rush_s),
                schedule_on_time_window_s=float(self.schedule_on_time_window_s),
                log_every_iters=int(self.log_every_iters),
            )

        out = self.make_single_task_proposal(
            proposal_id=pid,
            domain="MACRO_SPENDING",
            score=int(self.score),
            task_spec=TaskSpec(task_id="macro_spending", task_factory=_factory, unit_requirements=[]),
            lease_ttl=None,
            cooldown_s=0.0,
            risk_level=0,
            allow_preempt=True,
        )

        self.emit_planner_proposed({"count": len(out), "mode": "spending"})
        return out


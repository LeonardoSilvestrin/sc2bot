from __future__ import annotations

from dataclasses import dataclass

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.proposals import Proposal, TaskSpec
from bot.tasks.macro import (
    MacroAresBioStandardTick as MacroBio2BaseTick,
    MacroAresRushDefenseTick as MacroRushDefenseTick,
    MacroOpeningTick,
)
from bot.tasks.macro.scv_housekeeping_task import ScvHousekeeping


@dataclass
class MacroPlanner:
    planner_id: str = "macro_planner"
    score: int = 50
    backoff_urgency: int = 85

    # NEW: SCV housekeeping as a micro-task
    housekeeping_interval_s: float = 35.0
    housekeeping_cooldown_s: float = 6.0
    housekeeping_lease_ttl_s: float = 12.0
    housekeeping_score: int = 18
    log: DevLogger | None = None

    opening_task: MacroOpeningTick = None        # injected template
    bio_task: MacroBio2BaseTick = None           # injected template
    rush_defense_task: MacroRushDefenseTick = None  # injected template

    def _pid_opening(self) -> str:
        return f"{self.planner_id}:macro_opening"

    def _pid_bio(self) -> str:
        return f"{self.planner_id}:macro_bio_2base"

    def _pid_rush_def(self) -> str:
        return f"{self.planner_id}:macro_rush_defense"

    def _pid_housekeeping(self) -> str:
        return f"{self.planner_id}:scv_housekeeping"

    def _want_rush_defense(self, *, awareness: Awareness, attention: Attention) -> bool:
        return bool(attention.combat.threatened) and int(attention.combat.defense_urgency) >= 70

    def _housekeeping_due(self, *, awareness: Awareness, now: float) -> bool:
        last = awareness.mem.get(K("macro", "scv", "housekeeping", "last_done_at"), now=now, default=None)
        if last is None:
            return True
        try:
            return (float(now) - float(last)) >= float(self.housekeeping_interval_s)
        except Exception:
            return True

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)

        if self.opening_task is None or self.bio_task is None or self.rush_defense_task is None:
            raise TypeError("MacroPlanner requires opening_task, bio_task, rush_defense_task")

        # global backoff
        if bool(attention.combat.threatened) and int(attention.combat.defense_urgency) >= int(self.backoff_urgency):
            return []

        proposals: list[Proposal] = []

        # 0) SCV housekeeping micro-task (almost always acceptable; tiny cost)
        hk_pid = self._pid_housekeeping()
        if self._housekeeping_due(awareness=awareness, now=now):
            if not awareness.ops_proposal_running(proposal_id=hk_pid, now=now):

                def _hk_factory(mission_id: str) -> ScvHousekeeping:
                    return ScvHousekeeping(awareness=awareness)

                proposals.append(
                    Proposal(
                        proposal_id=hk_pid,
                        domain="MACRO",
                        score=int(self.housekeeping_score),
                        tasks=[
                            TaskSpec(
                                task_id="scv_housekeeping",
                                task_factory=_hk_factory,
                                unit_requirements=[],
                            )
                        ],
                        lease_ttl=float(self.housekeeping_lease_ttl_s),
                        cooldown_s=float(self.housekeeping_cooldown_s),
                        risk_level=0,
                        allow_preempt=True,
                    )
                )

        opening_done = bool(attention.macro.opening_done)
        want_rush = self._want_rush_defense(awareness=awareness, attention=attention)

        # OPENING
        if not opening_done:
            pid = self._pid_opening()

            def _factory(mission_id: str) -> MacroOpeningTick:
                return self.opening_task.spawn()

            proposals.append(
                Proposal(
                    proposal_id=pid,
                    domain="MACRO",
                    score=int(self.score),
                    tasks=[TaskSpec(task_id="macro_opening", task_factory=_factory, unit_requirements=[], lease_ttl=None)],
                    lease_ttl=None,
                    cooldown_s=0.0,
                    risk_level=0,
                    allow_preempt=True,
                )
            )
            if self.log is not None:
                self.log.emit(
                    "planner_proposed",
                    {"planner": self.planner_id, "count": len(proposals), "mode": "opening"},
                    meta={"module": "planner", "component": f"planner.{self.planner_id}"},
                )
            return proposals

        # RUSH DEFENSE
        if want_rush:
            pid = self._pid_rush_def()

            def _factory(mission_id: str) -> MacroRushDefenseTick:
                return self.rush_defense_task.spawn()

            proposals.append(
                Proposal(
                    proposal_id=pid,
                    domain="MACRO",
                    score=int(self.score) + 20,
                    tasks=[TaskSpec(task_id="macro_rush_defense", task_factory=_factory, unit_requirements=[], lease_ttl=None)],
                    lease_ttl=None,
                    cooldown_s=0.0,
                    risk_level=1,
                    allow_preempt=True,
                )
            )
            if self.log is not None:
                self.log.emit(
                    "planner_proposed",
                    {"planner": self.planner_id, "count": len(proposals), "mode": "rush_defense"},
                    meta={"module": "planner", "component": f"planner.{self.planner_id}"},
                )
            return proposals

        # NORMAL macro
        pid = self._pid_bio()

        def _factory(mission_id: str) -> MacroBio2BaseTick:
            return self.bio_task.spawn()

        proposals.append(
            Proposal(
                proposal_id=pid,
                domain="MACRO",
                score=int(self.score),
                tasks=[TaskSpec(task_id="macro_bio_2base", task_factory=_factory, unit_requirements=[], lease_ttl=None)],
                lease_ttl=None,
                cooldown_s=0.0,
                risk_level=0,
                allow_preempt=True,
            )
        )

        if self.log is not None:
            self.log.emit(
                "planner_proposed",
                {"planner": self.planner_id, "count": len(proposals), "mode": "bio"},
                meta={"module": "planner", "component": f"planner.{self.planner_id}"},
            )
        return proposals

# bot/planners/macro_planner.py
from __future__ import annotations

from dataclasses import dataclass

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.planners.proposals import Proposal, TaskSpec
from bot.tasks.macro_task import MacroBio2BaseTick, MacroOpeningTick


@dataclass
class MacroPlanner:
    """
    Planner baseline:
      - Enquanto opening do YAML não terminou: roda MacroOpeningTick.
      - Depois: roda MacroBio2BaseTick.
      - Sai do caminho quando o bot está sendo rushado (urgência alta).
    """
    planner_id: str = "macro_planner"

    opening_task: MacroOpeningTick = None  # template
    macro_task: MacroBio2BaseTick = None   # template

    backoff_urgency: int = 60
    opening_timeout_s: float = 180.0
    score: int = 18

    def _pid_opening(self) -> str:
        return f"{self.planner_id}:macro:opening"

    def _pid_macro(self) -> str:
        return f"{self.planner_id}:macro:bio_2base"

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        if bool(attention.combat.threatened) and int(attention.combat.defense_urgency) >= int(self.backoff_urgency):
            return []

        now = float(attention.time)

        if self.opening_task is None or self.macro_task is None:
            raise TypeError("MacroPlanner requires opening_task and macro_task template instances")

        opening_done = bool(attention.macro.opening_done)
        if opening_done or (now >= float(self.opening_timeout_s)):
            def _macro_factory(mission_id: str) -> MacroBio2BaseTick:
                return self.macro_task.spawn()

            return [
                Proposal(
                    proposal_id=self._pid_macro(),
                    domain="MACRO",
                    score=int(self.score),
                    tasks=[TaskSpec(task_id="macro_bio_2base_v01", task_factory=_macro_factory, unit_requirements=[])],
                    lease_ttl=2.5,
                    cooldown_s=0.0,
                    risk_level=1,
                    allow_preempt=True,
                )
            ]

        def _opening_factory(mission_id: str) -> MacroOpeningTick:
            return self.opening_task.spawn()

        return [
            Proposal(
                proposal_id=self._pid_opening(),
                domain="MACRO",
                score=int(self.score),
                tasks=[TaskSpec(task_id="macro_opening_scv_only", task_factory=_opening_factory, unit_requirements=[])],
                lease_ttl=2.5,
                cooldown_s=0.0,
                risk_level=0,
                allow_preempt=True,
            )
        ]
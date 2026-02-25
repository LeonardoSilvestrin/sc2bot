# bot/planners/macro_planner.py
from __future__ import annotations

from dataclasses import dataclass

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.planners.proposals import Proposal
from bot.tasks.macro_task import MacroBio2BaseTick, MacroOpeningTick


@dataclass
class MacroPlanner:
    """
    Planner baseline:
      - Enquanto opening do YAML não terminou: roda MacroOpeningTick (SCV-only).
      - Se opening terminar OU estourar timeout: roda MacroBio2BaseTick (full macro).
      - Sai do caminho quando o bot está sendo rushado (urgência alta).
    """
    planner_id: str = "macro_planner"

    def __init__(
        self,
        *,
        opening_task: MacroOpeningTick,
        macro_task: MacroBio2BaseTick,
        backoff_urgency: int = 60,
        opening_timeout_s: float = 180.0,
        score: int = 18,
    ):
        self.opening_task = opening_task
        self.macro_task = macro_task
        self.backoff_urgency = int(backoff_urgency)
        self.opening_timeout_s = float(opening_timeout_s)
        self.score = int(score)

    def _pid_opening(self) -> str:
        return f"{self.planner_id}:macro:opening_scv_only"

    def _pid_macro(self) -> str:
        return f"{self.planner_id}:macro:bio_2base"

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        # se ameaça relevante, deixa DEFENSE dominar
        if bool(attention.combat.threatened) and int(attention.combat.defense_urgency) >= self.backoff_urgency:
            return []

        now = float(getattr(attention, "time", 0.0))

        # Decide qual macro rodar (planner é dono da troca de fase)
        if bool(attention.macro.opening_done) or (now >= self.opening_timeout_s):
            reason = "opening_done" if attention.macro.opening_done else f"opening_timeout_skip t={round(now,1)}>= {round(self.opening_timeout_s,1)}"

            def _macro_factory(mission_id: str) -> MacroBio2BaseTick:
                t = self.macro_task
                try:
                    setattr(t, "mission_id", mission_id)
                except Exception:
                    pass
                return t

            return [
                Proposal(
                    proposal_id=self._pid_macro(),
                    domain="MACRO",
                    score=self.score,
                    task_factory=_macro_factory,
                    unit_requirements=[],
                    lease_ttl=8.0,      # macro não precisa travar unidades por muito tempo
                    cooldown_s=0.0,     # macro é baseline, não queremos cooldown
                    risk_level=0,
                    allow_preempt=True,
                )
            ]

        def _opening_factory(mission_id: str) -> MacroOpeningTick:
            t = self.opening_task
            try:
                setattr(t, "mission_id", mission_id)
            except Exception:
                pass
            return t

        return [
            Proposal(
                proposal_id=self._pid_opening(),
                domain="MACRO",
                score=self.score,
                task_factory=_opening_factory,
                unit_requirements=[],
                lease_ttl=8.0,
                cooldown_s=0.0,
                risk_level=0,
                allow_preempt=True,
            )
        ]
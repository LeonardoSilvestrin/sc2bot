# bot/planners/macro_planner.py
from __future__ import annotations

from dataclasses import dataclass

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.planners.proposals import Proposal
from bot.tasks.macro import MacroBasic


@dataclass
class MacroPlanner:
    """
    Planner baseline:
      - Propõe MACRO praticamente sempre (SCV contínuo).
      - Sai do caminho quando o bot está sendo rushado (urgência alta).
    """
    planner_id: str = "macro_planner"

    def __init__(self, *, macro_task: MacroBasic, backoff_urgency: int = 60):
        self.macro_task = macro_task
        self.backoff_urgency = int(backoff_urgency)

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        # Se a base está sob ameaça relevante, deixa DEFENSE dominar o budget.
        if attention.threatened and int(attention.defense_urgency) >= self.backoff_urgency:
            return []

        # Score constante e baixo/moderado:
        # - garante que MACRO exista como baseline
        # - mas perde naturalmente para DEFENSE (ordenado primeiro) e para INTEL quando necessário
        score = 18

        return [
            Proposal(
                domain="MACRO",
                score=int(score),
                task=self.macro_task,
                reason="baseline_macro_scv",
            )
        ]
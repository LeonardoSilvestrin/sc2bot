# bot/planners/defense_planner.py
from __future__ import annotations

from dataclasses import dataclass

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.planners.proposals import Proposal
from bot.tasks.defend_task import Defend


@dataclass
class DefensePlanner:
    """
    Planner reativo de defesa.
    - Só propõe quando há ameaça.
    - Score escala com urgência (Attention.defense_urgency).
    - Não redefine Proposal/UnitRequirement (usa o contrato único em planners/proposals.py).
    """
    planner_id: str = "defense_planner"

    awareness: Awareness = None  # injected
    defend_task: Defend = None   # injected

    def _pid_defend(self) -> str:
        return f"{self.planner_id}:defend:bases"

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        """
        v2 contract:
          - Proposal(proposal_id, domain, score, task_factory, unit_requirements, .)
        """
        if (not bool(attention.combat.threatened)) or (not attention.combat.threat_pos):
            return []

        urg = int(getattr(attention.combat, "defense_urgency", 0))
        # DEFENSE deve dominar quando houver ameaça: score alto e proporcional.
        score = max(80, min(100, 60 + urg))

        def _defend_factory(mission_id: str) -> Defend:
            t = self.defend_task
            try:
                setattr(t, "mission_id", mission_id)
            except Exception:
                pass
            return t

        return [
            Proposal(
                proposal_id=self._pid_defend(),
                domain="DEFENSE",
                score=score,
                task_factory=_defend_factory,
                unit_requirements=[],   # MVP: Defend puxa “defenders” do bot; depois a gente amarra via Body.
                lease_ttl=6.0,
                cooldown_s=0.0,         # defesa não deve “cooldownar”
                risk_level=0,
                allow_preempt=True,
            )
        ]
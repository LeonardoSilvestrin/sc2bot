# bot/behaviors/plan.py
from __future__ import annotations

from typing import Any

from .base import TickBudget


class PlanBehavior:
    name = "plan"

    def __init__(self, plan_executor: Any):
        self.plan = plan_executor

    async def step(self, budget: TickBudget, cfg: dict) -> bool:
        # o PlanExecutor já tem sua própria política de 1 ação por tick (do jeito que você escreveu)
        # então aqui, se não tem budget, nem roda.
        if budget.remaining <= 0:
            return False

        before = getattr(self.plan.builder, "last", None)
        await self.plan.step()

        # se o plan executou algo “relevante”, ele terá action_ok no logger,
        # mas pra consumir budget sem depender de log, usa heuristic simples:
        after = getattr(self.plan.builder, "last", None)
        did = bool(after is not None and after is not before and getattr(after, "reason", "") == "ok")

        if did:
            budget.spend(1)
        return did
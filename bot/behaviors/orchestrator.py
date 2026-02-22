# behaviors/orchestrator.py
from __future__ import annotations

from typing import Any, Iterable, List

from .base import TickBudget, Behavior


class BehaviorOrchestrator:
    """
    Roda behaviors em ordem e respeita budget de ações por tick.
    """

    def __init__(self, behaviors: Iterable[Behavior]):
        self.behaviors: List[Behavior] = list(behaviors)

    async def step(self, *, budget_actions: int = 1) -> None:
        budget = TickBudget(remaining=int(budget_actions))
        for b in self.behaviors:
            if budget.remaining <= 0:
                return
            did = await b.step(budget)
            # se você quiser “um comportamento por tick”, descomenta:
            # if did:
            #     return
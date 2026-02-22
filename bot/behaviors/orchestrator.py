# bot/behaviors/orchestrator.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Tuple

from .base import TickBudget


@dataclass
class ActiveBehavior:
    behavior: Any
    cfg: dict


class BehaviorOrchestrator:
    def __init__(self):
        self.active: List[ActiveBehavior] = []

    def set_active(self, pairs: Iterable[Tuple[Any, dict]]) -> None:
        self.active = [ActiveBehavior(b, cfg) for (b, cfg) in pairs]

    async def step(self, *, budget_actions: int = 1) -> None:
        budget = TickBudget(remaining=int(budget_actions))
        for ab in self.active:
            if budget.remaining <= 0:
                return
            # contrato novo: step(budget, cfg) -> bool
            await ab.behavior.step(budget, ab.cfg)
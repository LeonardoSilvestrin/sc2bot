# behaviors/base.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class TickBudget:
    remaining: int = 1

    def spend(self, n: int = 1) -> bool:
        if self.remaining < n:
            return False
        self.remaining -= n
        return True


class Behavior(Protocol):
    """Contrato único. Config NÃO fica no __init__."""
    name: str

    async def step(self, budget: TickBudget, cfg: Any) -> bool:
        """
        Retorna True se emitiu ação relevante (normalmente gasta budget).
        """
        ...
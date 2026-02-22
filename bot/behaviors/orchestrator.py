#bot/behaviors/orchestrator.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Tuple, Optional

from .base import TickBudget


@dataclass
class ActiveBehavior:
    behavior: Any
    cfg: dict
    key: str  # id estável por behavior


class BehaviorOrchestrator:
    """
    Round-robin estável entre ticks.
    Agora usa uma chave estável se o behavior expõe .key (ex.: drops).
    """

    def __init__(self):
        self.active: List[ActiveBehavior] = []
        self._rr_index: int = 0
        self._last_keys: List[str] = []

    def _mk_key(self, behavior: Any) -> str:
        name = getattr(behavior, "name", behavior.__class__.__name__)
        stable = getattr(behavior, "key", None)
        if stable is not None:
            return f"{name}:{stable}"
        return f"{name}:{id(behavior)}"

    def set_active(self, pairs: Iterable[Tuple[Any, dict]]) -> None:
        new_active: List[ActiveBehavior] = []
        new_keys: List[str] = []

        for b, cfg in pairs:
            k = self._mk_key(b)
            new_active.append(ActiveBehavior(behavior=b, cfg=cfg, key=k))
            new_keys.append(k)

        if self._last_keys and new_keys and new_keys != self._last_keys:
            old_next_key: Optional[str] = None
            if 0 <= self._rr_index < len(self._last_keys):
                old_next_key = self._last_keys[self._rr_index]
            if old_next_key in new_keys:
                self._rr_index = new_keys.index(old_next_key)
            else:
                self._rr_index = 0

        self.active = new_active
        self._last_keys = new_keys

        if self._rr_index >= len(self.active):
            self._rr_index = 0

    async def step(self, *, budget_actions: int = 1) -> None:
        if not self.active:
            return

        budget = TickBudget(remaining=int(budget_actions))
        n = len(self.active)
        start = self._rr_index % n

        for i in range(n):
            if budget.remaining <= 0:
                break

            idx = (start + i) % n
            ab = self.active[idx]

            did = await ab.behavior.step(budget, ab.cfg)

            if did:
                self._rr_index = (idx + 1) % n
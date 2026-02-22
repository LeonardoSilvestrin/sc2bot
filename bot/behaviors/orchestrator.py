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
    Agenda behaviors com Round-Robin real.
    - Mantém ponteiro (_rr_index) ESTÁVEL entre ticks usando `key`.
    - Se a lista de behaviors muda (ativou/desativou), tenta preservar justiça.
    - Contrato: behavior.step(budget, cfg) -> bool (True se consumiu 1 action do budget)
    """

    def __init__(self):
        self.active: List[ActiveBehavior] = []
        self._rr_index: int = 0
        self._last_keys: List[str] = []

    def _mk_key(self, behavior: Any) -> str:
        # nome + id garante unicidade de instâncias (você tem múltiplos drops)
        name = getattr(behavior, "name", behavior.__class__.__name__)
        return f"{name}:{id(behavior)}"

    def set_active(self, pairs: Iterable[Tuple[Any, dict]]) -> None:
        new_active: List[ActiveBehavior] = []
        new_keys: List[str] = []

        for b, cfg in pairs:
            k = self._mk_key(b)
            new_active.append(ActiveBehavior(behavior=b, cfg=cfg, key=k))
            new_keys.append(k)

        # Se keys mudaram, tenta manter o ponteiro "apontando" para o mesmo próximo behavior
        if self._last_keys and new_keys:
            if new_keys != self._last_keys:
                # behavior que seria o próximo no ciclo antigo
                old_next_key: Optional[str] = None
                if 0 <= self._rr_index < len(self._last_keys):
                    old_next_key = self._last_keys[self._rr_index]

                if old_next_key in new_keys:
                    self._rr_index = new_keys.index(old_next_key)
                else:
                    # fallback seguro
                    self._rr_index = 0

        # atualiza
        self.active = new_active
        self._last_keys = new_keys

        # clamp final
        if self._rr_index >= len(self.active):
            self._rr_index = 0

    async def step(self, *, budget_actions: int = 1) -> None:
        if not self.active:
            return

        budget = TickBudget(remaining=int(budget_actions))
        n = len(self.active)
        start = self._rr_index % n

        # percorre todos a partir do start (RR)
        for i in range(n):
            if budget.remaining <= 0:
                break

            idx = (start + i) % n
            ab = self.active[idx]

            did = await ab.behavior.step(budget, ab.cfg)

            # se consumiu 1 action, o próximo tick começa depois dele
            if did:
                self._rr_index = (idx + 1) % n
                # NÃO quebra: ainda pode sobrar budget pra mais 1 action
                # e é exatamente isso que você quer com 2 drops (budget=2).
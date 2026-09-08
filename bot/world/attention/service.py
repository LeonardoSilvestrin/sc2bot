from __future__ import annotations

from .facts import WorldFacts
from .snapshot import AttentionSnapshot


class AttentionService:
    """Turns already-collected ``WorldFacts`` into an ``AttentionSnapshot``.

    Collecting the facts themselves (reading ``bot``/``mediator``/Ares) is
    not this service's job -- see ``bot.adapters.ares.AresWorldObserver``.
    """

    @staticmethod
    def build(*, world: WorldFacts) -> AttentionSnapshot:
        return AttentionSnapshot(world=world)

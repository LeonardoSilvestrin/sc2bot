from __future__ import annotations

from dataclasses import dataclass

from .world_facts import WorldFacts


@dataclass(frozen=True, slots=True)
class AttentionSnapshot:
    """Selected, immutable observations from the current game frame."""

    world: WorldFacts

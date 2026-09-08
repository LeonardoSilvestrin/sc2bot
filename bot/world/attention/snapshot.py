from __future__ import annotations

from dataclasses import dataclass

from .facts import WorldFacts


@dataclass(frozen=True, slots=True)
class AttentionSnapshot:
    """Selected, immutable observations from the current game frame.

    Today this only wraps ``WorldFacts`` -- there is no filtering, grouping,
    or saliency scoring yet. The package is shaped so that kind of selection
    (e.g. ``attention/enemy/``, ``attention/bases/``) can be added next to
    ``facts/`` once a real need for it shows up, without disturbing
    ``WorldFacts`` or its consumers.
    """

    world: WorldFacts

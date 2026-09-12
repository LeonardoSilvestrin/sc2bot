from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..enemy.heuristics import freshness


@dataclass(slots=True)
class ObservationMemory:
    """When each lattice sample was last in our vision.

    Attention only reports what is visible now; this remembers it. It is
    recorded every frame, so a scout crossing a place between two territory
    updates still counts as a look at it.
    """

    _seen_at: list[float | None] = field(default_factory=list)

    def reset(self, count: int) -> None:
        self._seen_at = [None] * count

    def record(self, visibility: Sequence[bool], now: float) -> None:
        # A visibility report for another lattice says nothing about this one.
        if len(visibility) != len(self._seen_at):
            return
        for index, visible in enumerate(visibility):
            if visible:
                self._seen_at[index] = now

    def quality(self, index: int | None, now: float, stale_after: float) -> float:
        """1.0 while in vision, fading linearly to 0 over ``stale_after``;
        0 for a place never seen."""

        if index is None or index >= len(self._seen_at):
            return 0.0
        seen_at = self._seen_at[index]
        return 0.0 if seen_at is None else freshness(now - seen_at, stale_after)

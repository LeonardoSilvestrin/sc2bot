from __future__ import annotations

from typing import Protocol

from sc2.position import Point2


class VisionCommands(Protocol):
    """Adapter operations used by active-vision providers."""

    def has_vision(self, position: Point2) -> bool:
        ...

    def scan(self, *, orbital_tag: int, target: Point2) -> bool:
        ...

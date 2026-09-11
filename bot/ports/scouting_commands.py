from __future__ import annotations

from typing import Protocol

from sc2.position import Point2


class ScoutingCommands(Protocol):
    """Map-information commands which do not require a mobile-unit lease."""

    def scan(self, *, orbital_tag: int, target: Point2) -> bool:
        """Try to cast Scanner Sweep, returning whether the command was accepted."""
        ...

from __future__ import annotations

from typing import Protocol

from sc2.position import Point2


class MissionCommands(Protocol):
    """Authorized execution operations available to mission executors."""

    def path_to(
        self,
        *,
        mission_id: str,
        unit_tag: int,
        target: Point2,
        success_at_distance: float,
    ) -> None:
        ...

    def release(self, *, mission_id: str, unit_tag: int) -> None:
        ...

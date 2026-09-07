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


class EconomyCommands(Protocol):
    """Authorized execution operations available to the economy controller."""

    def produce_worker(self, *, to_count: int) -> None:
        ...

    def produce_supply(self, *, base_location: Point2) -> None:
        ...

    def expand(self, *, to_count: int) -> None:
        ...

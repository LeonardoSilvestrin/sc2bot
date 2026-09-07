from __future__ import annotations

from typing import Protocol

from sc2.ids.ability_id import AbilityId
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

    def attack_move(
        self,
        *,
        mission_id: str,
        unit_tag: int,
        target: Point2,
        success_at_distance: float,
    ) -> None:
        ...

    def attack_unit(
        self,
        *,
        mission_id: str,
        unit_tag: int,
        target_unit_tag: int,
    ) -> None:
        ...

    def safe_path_to(
        self,
        *,
        mission_id: str,
        unit_tag: int,
        target: Point2,
        success_at_distance: float,
        search_radius: float = 14.0,
    ) -> None:
        ...

    def release(self, *, mission_id: str, unit_tag: int) -> None:
        ...

    def use_ability(
        self,
        *,
        mission_id: str,
        unit_tag: int,
        ability: AbilityId,
    ) -> None:
        ...

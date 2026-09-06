from __future__ import annotations

from typing import Protocol

from sc2.position import Point2


class ActionCommands(Protocol):
    """The only way an action may issue commands to owned units."""

    def move(
        self, *, action_id: str, unit_tag: int, target: Point2, queue: bool = False
    ) -> None: ...

    def attack(
        self, *, action_id: str, unit_tag: int, target: Point2, queue: bool = False
    ) -> None: ...

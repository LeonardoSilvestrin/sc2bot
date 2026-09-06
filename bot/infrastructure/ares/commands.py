from __future__ import annotations

from sc2.position import Point2

from bot.units.registry import UnitRegistry


class UnauthorizedUnitCommand(RuntimeError):
    pass


class AresActionCommands:
    """Validates unit ownership before forwarding commands to python-sc2."""

    def __init__(self, bot, registry: UnitRegistry) -> None:
        self._bot = bot
        self._registry = registry

    def _unit(self, *, action_id: str, unit_tag: int):
        if self._registry.owner_of(unit_tag) != action_id:
            raise UnauthorizedUnitCommand(
                f"action {action_id!r} does not own unit {unit_tag}"
            )
        unit = self._bot.unit_tag_dict.get(unit_tag)
        if unit is None:
            raise LookupError(f"unit {unit_tag} is no longer available")
        return unit

    def move(
        self, *, action_id: str, unit_tag: int, target: Point2, queue: bool = False
    ) -> None:
        self._unit(action_id=action_id, unit_tag=unit_tag).move(target, queue=queue)

    def attack(
        self, *, action_id: str, unit_tag: int, target: Point2, queue: bool = False
    ) -> None:
        self._unit(action_id=action_id, unit_tag=unit_tag).attack(target, queue=queue)

from __future__ import annotations

from sc2.position import Point2

from bot.ego.allocator import UnitAllocator


class UnauthorizedUnitCommand(RuntimeError):
    pass


class AresMissionCommands:
    """Validates leases and translates mission intent into Ares behaviors."""

    def __init__(self, bot, allocator: UnitAllocator) -> None:
        self._bot = bot
        self._allocator = allocator

    def _unit(self, *, mission_id: str, unit_tag: int):
        self._authorize(mission_id=mission_id, unit_tag=unit_tag)
        unit = self._bot.unit_tag_dict.get(unit_tag)
        if unit is None:
            raise LookupError(f"unit {unit_tag} is no longer available")
        return unit

    def _authorize(self, *, mission_id: str, unit_tag: int) -> None:
        if self._allocator.owner_of(unit_tag) != mission_id:
            raise UnauthorizedUnitCommand(
                f"mission {mission_id!r} does not own unit {unit_tag}"
            )

    def path_to(
        self,
        *,
        mission_id: str,
        unit_tag: int,
        target: Point2,
        success_at_distance: float,
    ) -> None:
        unit = self._unit(mission_id=mission_id, unit_tag=unit_tag)
        # Local imports keep Ares behind the infrastructure boundary.
        from ares.behaviors.combat.individual import PathUnitToTarget
        from ares.consts import UnitRole

        if unit.type_id == self._bot.worker_type:
            self._bot.mediator.remove_worker_from_mineral(worker_tag=unit_tag)
        self._bot.mediator.assign_role(tag=unit_tag, role=UnitRole.SCOUTING)
        self._bot.register_behavior(
            PathUnitToTarget(
                unit=unit,
                grid=self._bot.mediator.get_ground_grid,
                target=target,
                success_at_distance=success_at_distance,
            )
        )

    def release(self, *, mission_id: str, unit_tag: int) -> None:
        self._authorize(mission_id=mission_id, unit_tag=unit_tag)
        unit = self._bot.unit_tag_dict.get(unit_tag)
        if unit is None:
            return
        from ares.consts import UnitRole

        role = (
            UnitRole.GATHERING
            if unit.type_id == self._bot.worker_type
            else UnitRole.IDLE
        )
        self._bot.mediator.assign_role(tag=unit_tag, role=role)

from __future__ import annotations

from sc2.position import Point2

from bot.engine.missions.allocator import UnitAllocator


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
        # Local imports keep Ares behind the adapter boundary.
        from ares.behaviors.combat import CombatManeuver
        from ares.behaviors.combat.individual import KeepUnitSafe, PathUnitToTarget
        from ares.consts import UnitRole

        if unit.type_id == self._bot.worker_type:
            self._bot.mediator.remove_worker_from_mineral(worker_tag=unit_tag)
        self._bot.mediator.assign_role(tag=unit_tag, role=UnitRole.SCOUTING)
        grid = (
            self._bot.mediator.get_climber_grid
            if unit.type_id.name == "REAPER"
            else self._bot.mediator.get_ground_grid
        )
        maneuver = CombatManeuver()
        maneuver.add(KeepUnitSafe(unit=unit, grid=grid))
        maneuver.add(
            PathUnitToTarget(
                unit=unit,
                grid=grid,
                target=target,
                success_at_distance=success_at_distance,
                sense_danger=True,
                danger_distance=24.0,
                danger_threshold=1.0,
            )
        )
        self._bot.register_behavior(maneuver)

    def attack_move(
        self,
        *,
        mission_id: str,
        unit_tag: int,
        target: Point2,
        success_at_distance: float,
    ) -> None:
        unit = self._unit(mission_id=mission_id, unit_tag=unit_tag)
        # Local imports keep Ares behind the adapter boundary.
        from ares.behaviors.combat.individual import AMove
        from ares.consts import UnitRole

        self._bot.mediator.assign_role(tag=unit_tag, role=UnitRole.ATTACKING)
        self._bot.register_behavior(
            AMove(unit=unit, target=target, success_at_distance=success_at_distance)
        )

    def attack_unit(
        self,
        *,
        mission_id: str,
        unit_tag: int,
        target_unit_tag: int,
    ) -> None:
        unit = self._unit(mission_id=mission_id, unit_tag=unit_tag)
        target = self._bot.unit_tag_dict.get(target_unit_tag)
        if target is None:
            raise LookupError(f"enemy unit {target_unit_tag} is no longer available")

        from ares.behaviors.combat import CombatManeuver
        from ares.behaviors.combat.individual import (
            ReaperGrenade,
            StutterUnitForward,
        )
        from ares.consts import UnitRole

        self._bot.mediator.assign_role(tag=unit_tag, role=UnitRole.HARASSING)
        maneuver = CombatManeuver()
        if unit.type_id.name == "REAPER":
            maneuver.add(
                ReaperGrenade(
                    unit=unit,
                    enemy_units=list(self._bot.enemy_units),
                    retreat_target=self._bot.start_location,
                    grid=self._bot.mediator.get_climber_grid,
                )
            )
        maneuver.add(StutterUnitForward(unit=unit, target=target))
        self._bot.register_behavior(maneuver)

    def safe_path_to(
        self,
        *,
        mission_id: str,
        unit_tag: int,
        target: Point2,
        success_at_distance: float,
        search_radius: float = 14.0,
    ) -> None:
        unit = self._unit(mission_id=mission_id, unit_tag=unit_tag)
        from ares.behaviors.combat.individual import MoveToSafeTarget
        from ares.consts import UnitRole

        self._bot.mediator.assign_role(tag=unit_tag, role=UnitRole.MAP_CONTROL)
        grid = (
            self._bot.mediator.get_climber_grid
            if unit.type_id.name == "REAPER"
            else self._bot.mediator.get_ground_grid
        )
        self._bot.register_behavior(
            MoveToSafeTarget(
                unit=unit,
                grid=grid,
                target=target,
                success_at_distance=success_at_distance,
                sense_danger=True,
                danger_distance=24.0,
                danger_threshold=1.0,
                radius=search_radius,
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

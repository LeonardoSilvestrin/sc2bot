from __future__ import annotations

from sc2.position import Point2

from bot.attention.models import (
    AttentionSnapshot,
    MapFacts,
    MapObservation,
    UnitSnapshot,
    WorldFacts,
)


class AttentionBuilder:
    """The sole adapter that turns mutable Ares state into immutable facts."""

    @staticmethod
    def _unit_snapshot(
        bot, unit, *, visible_now: bool, available_for_mission: bool = True
    ) -> UnitSnapshot:
        return UnitSnapshot(
            tag=int(unit.tag),
            unit_type=unit.type_id,
            position=unit.position,
            health_percentage=float(unit.health_percentage),
            is_flying=bool(unit.is_flying),
            is_worker=bool(unit.type_id == bot.worker_type),
            can_attack_air=bool(unit.can_attack_air),
            can_attack_ground=bool(unit.can_attack_ground),
            visible_now=visible_now,
            is_ready=bool(getattr(unit, "is_ready", True)),
            is_carrying_resource=bool(getattr(unit, "is_carrying_resource", False)),
            is_structure=bool(getattr(unit, "is_structure", False)),
            is_constructing=bool(getattr(unit, "is_constructing_scv", False)),
            available_for_mission=available_for_mission,
        )

    @staticmethod
    def _unavailable_unit_tags(bot) -> set[int] | None:
        try:
            roles = bot.mediator.get_unit_role_dict
        except (AttributeError, KeyError, RuntimeError):
            return None
        unavailable: set[int] = set()
        for role, tags in roles.items():
            role_name = getattr(role, "name", str(role))
            if role_name not in {"GATHERING", "IDLE"}:
                unavailable.update(int(tag) for tag in tags)
        return unavailable

    @staticmethod
    def _map_observations(bot) -> tuple[MapObservation, ...]:
        selected: list[tuple[str, Point2]] = []
        enemy_starts = tuple(bot.enemy_start_locations)
        if enemy_starts:
            selected.append(("enemy_main", enemy_starts[0]))
        try:
            enemy_natural = bot.mediator.get_enemy_nat
        except (AttributeError, KeyError, RuntimeError):
            enemy_natural = None
        if enemy_natural is not None:
            selected.append(("enemy_natural", enemy_natural))

        is_visible = getattr(bot, "is_visible", None)
        return tuple(
            MapObservation(
                key=key,
                position=position,
                visible_now=bool(is_visible(position))
                if callable(is_visible)
                else False,
            )
            for key, position in selected
        )

    def world_facts(self, bot, *, iteration: int) -> WorldFacts:
        unavailable_units = self._unavailable_unit_tags(bot)
        own_units = tuple(
            self._unit_snapshot(
                bot,
                unit,
                visible_now=True,
                available_for_mission=(
                    unavailable_units is None or int(unit.tag) not in unavailable_units
                ),
            )
            for unit in bot.units
        )
        own_structures = tuple(
            self._unit_snapshot(bot, unit, visible_now=True)
            for unit in getattr(bot, "structures", ())
        )
        enemy_units = tuple(
            self._unit_snapshot(bot, unit, visible_now=True)
            for unit in getattr(bot, "enemy_units", ())
            if not bool(getattr(unit, "is_memory", False))
        )
        enemy_structures = tuple(
            self._unit_snapshot(bot, unit, visible_now=True)
            for unit in getattr(bot, "enemy_structures", ())
            if not bool(getattr(unit, "is_memory", False))
        )
        return WorldFacts(
            iteration=int(iteration),
            time=float(bot.time),
            minerals=int(bot.minerals),
            vespene=int(bot.vespene),
            supply_used=float(bot.supply_used),
            supply_cap=float(bot.supply_cap),
            own_units=own_units,
            enemy_units=enemy_units,
            map=MapFacts(
                center=bot.game_info.map_center,
                own_start=bot.start_location,
                enemy_starts=tuple(bot.enemy_start_locations),
                observations=self._map_observations(bot),
            ),
            own_structures=own_structures,
            enemy_structures=enemy_structures,
        )

    @staticmethod
    def build(
        *,
        world: WorldFacts,
    ) -> AttentionSnapshot:
        return AttentionSnapshot(world=world)

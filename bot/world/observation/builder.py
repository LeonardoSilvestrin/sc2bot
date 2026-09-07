from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping

from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.world.observation.models import (
    AttentionSnapshot,
    CountFacts,
    EconomyFacts,
    MapFacts,
    MapObservation,
    ProducerFacts,
    UnitSnapshot,
    UnitTypeCount,
    WorldFacts,
)

_TOWNHALL_TYPES: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.COMMANDCENTER,
        UnitTypeId.ORBITALCOMMAND,
        UnitTypeId.PLANETARYFORTRESS,
        UnitTypeId.NEXUS,
        UnitTypeId.HATCHERY,
        UnitTypeId.LAIR,
        UnitTypeId.HIVE,
    }
)
_KNOWN_STRUCTURE_TYPES: frozenset[UnitTypeId] = frozenset(
    {
        *_TOWNHALL_TYPES,
        UnitTypeId.SUPPLYDEPOT,
        UnitTypeId.SUPPLYDEPOTLOWERED,
        UnitTypeId.PYLON,
        UnitTypeId.REFINERY,
        UnitTypeId.ASSIMILATOR,
        UnitTypeId.EXTRACTOR,
    }
)


def _ability_value(value) -> int | None:
    """Normalize AbilityId/AbilityData/fake ability values to an integer."""

    current = value
    for _ in range(4):
        if isinstance(current, int):
            return int(current)
        for attribute in ("exact_id", "id", "value"):
            try:
                candidate = getattr(current, attribute)
            except (AttributeError, KeyError, RuntimeError, TypeError):
                continue
            if candidate is not current:
                current = candidate
                break
        else:
            break
    try:
        return int(current)
    except (TypeError, ValueError):
        return None


_UNIT_BY_TRAIN_ABILITY: dict[int, UnitTypeId] = {}
for _trainable_units in TRAIN_INFO.values():
    for _trained_type, _train_info in _trainable_units.items():
        if (_value := _ability_value(_train_info.get("ability"))) is not None:
            _UNIT_BY_TRAIN_ABILITY[_value] = _trained_type


class AttentionBuilder:
    """The sole adapter that turns mutable Ares state into immutable facts."""

    @staticmethod
    def _safe_attr(obj, name: str, default=None):
        try:
            return getattr(obj, name, default)
        except (AttributeError, KeyError, RuntimeError, TypeError):
            return default

    @classmethod
    def _items(cls, obj, name: str) -> tuple:
        value = cls._safe_attr(obj, name, ())
        try:
            return tuple(value) if value is not None else ()
        except (RuntimeError, TypeError):
            return ()

    @staticmethod
    def _count(value) -> int:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0
        if not math.isfinite(number) or number <= 0.0:
            return 0
        return math.ceil(number)

    @staticmethod
    def _rate(value) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return number if math.isfinite(number) and number >= 0.0 else 0.0

    @classmethod
    def _mapping(cls, obj, *names: str) -> Mapping:
        for name in names:
            value = cls._safe_attr(obj, name)
            if callable(value):
                try:
                    value = value()
                except (AttributeError, KeyError, RuntimeError, TypeError):
                    continue
            if isinstance(value, Mapping):
                return value
        return {}

    @classmethod
    def _pending_count(
        cls,
        bot,
        unit_type: UnitTypeId,
        *,
        structure: bool,
        explicit: Mapping,
        fallback: int = 0,
    ) -> int:
        values = [fallback, cls._count(explicit.get(unit_type, 0))]
        method_names = (
            ("structure_pending", "already_pending")
            if structure
            else ("unit_pending", "already_pending")
        )
        for name in method_names:
            method = cls._safe_attr(bot, name)
            if not callable(method):
                continue
            try:
                values.append(cls._count(method(unit_type)))
            except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
                continue
        return max(values)

    @classmethod
    def _looks_like_structure(
        cls,
        bot,
        unit_type: UnitTypeId,
        known_structure_types: set[UnitTypeId],
    ) -> bool:
        if unit_type in known_structure_types or unit_type in _KNOWN_STRUCTURE_TYPES:
            return True

        game_data = cls._safe_attr(bot, "game_data")
        units_data = cls._safe_attr(game_data, "units")
        try:
            type_data = units_data[unit_type.value]
        except (AttributeError, IndexError, KeyError, TypeError):
            return False
        attributes = cls._safe_attr(type_data, "attributes", ())
        return any(
            getattr(attribute, "name", "") == "Structure"
            or getattr(attribute, "value", attribute) == 8
            for attribute in attributes
        )

    @classmethod
    def _build_order_types(cls, bot) -> set[UnitTypeId]:
        runner = cls._safe_attr(bot, "build_order_runner")
        build_order = cls._safe_attr(runner, "build_order", ())
        try:
            steps = tuple(build_order or ())
        except (RuntimeError, TypeError):
            return set()
        result: set[UnitTypeId] = set()
        for step in steps:
            command = cls._safe_attr(step, "command", step)
            if isinstance(command, UnitTypeId):
                result.add(command)
        return result

    @classmethod
    def _order_pending_counts(cls, units: tuple) -> Counter[UnitTypeId]:
        result: Counter[UnitTypeId] = Counter()
        for unit in units:
            orders = cls._safe_attr(unit, "orders", ())
            try:
                order_items = tuple(orders or ())
            except (RuntimeError, TypeError):
                continue
            for order in order_items:
                ability = cls._safe_attr(order, "ability")
                if (
                    (ability_id := _ability_value(ability)) is not None
                    and (unit_type := _UNIT_BY_TRAIN_ABILITY.get(ability_id))
                    is not None
                ):
                    result[unit_type] += 1
        return result

    @classmethod
    def _harvester_totals(
        cls, bot, own_structures: tuple
    ) -> tuple[int, int]:
        resource_structures = [
            *cls._items(bot, "townhalls"),
            *cls._items(bot, "gas_buildings"),
        ]
        if not resource_structures:
            resource_structures = [
                structure
                for structure in own_structures
                if cls._safe_attr(structure, "ideal_harvesters") is not None
                or cls._safe_attr(structure, "assigned_harvesters") is not None
            ]

        unique_structures: dict[object, object] = {}
        for structure in resource_structures:
            key = cls._safe_attr(structure, "tag", id(structure))
            unique_structures[key] = structure
        ideal = sum(
            cls._count(cls._safe_attr(structure, "ideal_harvesters", 0))
            for structure in unique_structures.values()
        )
        assigned = sum(
            cls._count(cls._safe_attr(structure, "assigned_harvesters", 0))
            for structure in unique_structures.values()
        )

        direct_ideal = cls._safe_attr(bot, "ideal_harvesters")
        direct_assigned = cls._safe_attr(bot, "assigned_harvesters")
        if direct_ideal is not None:
            ideal = cls._count(direct_ideal)
        if direct_assigned is not None:
            assigned = cls._count(direct_assigned)
        return ideal, assigned

    @classmethod
    def _economy_facts(
        cls,
        bot,
        *,
        own_units: tuple,
        own_structures: tuple,
    ) -> EconomyFacts:
        unit_existing = Counter(
            cls._safe_attr(unit, "type_id") for unit in own_units
        )
        unit_ready = Counter(
            cls._safe_attr(unit, "type_id")
            for unit in own_units
            if bool(cls._safe_attr(unit, "is_ready", True))
        )
        structure_existing = Counter(
            cls._safe_attr(structure, "type_id") for structure in own_structures
        )
        structure_ready = Counter(
            cls._safe_attr(structure, "type_id")
            for structure in own_structures
            if bool(cls._safe_attr(structure, "is_ready", True))
        )
        unit_existing.pop(None, None)
        unit_ready.pop(None, None)
        structure_existing.pop(None, None)
        structure_ready.pop(None, None)

        order_pending = cls._order_pending_counts((*own_units, *own_structures))
        mediator = cls._safe_attr(bot, "mediator")
        building_counter = cls._mapping(mediator, "get_building_counter")
        explicit_unit_pending = cls._mapping(
            bot, "pending_units", "unit_pending_counts"
        )
        explicit_structure_pending = cls._mapping(
            bot, "pending_structures", "structure_pending_counts"
        )

        structure_types = set(structure_existing)
        structure_types.update(
            key for key in building_counter if isinstance(key, UnitTypeId)
        )
        structure_types.update(
            key for key in explicit_structure_pending if isinstance(key, UnitTypeId)
        )
        for attribute in ("base_townhall_type", "supply_type", "gas_type"):
            if (
                isinstance(value := cls._safe_attr(bot, attribute), UnitTypeId)
                and value != UnitTypeId.OVERLORD
            ):
                structure_types.add(value)

        known_structure_types = set(structure_types)
        build_order_types = cls._build_order_types(bot)
        for unit_type in (*build_order_types, *order_pending):
            if cls._looks_like_structure(bot, unit_type, known_structure_types):
                structure_types.add(unit_type)

        unit_types = set(unit_existing)
        unit_types.update(
            key for key in explicit_unit_pending if isinstance(key, UnitTypeId)
        )
        worker_type = cls._safe_attr(bot, "worker_type")
        if isinstance(worker_type, UnitTypeId):
            unit_types.add(worker_type)
        for structure_type in structure_existing:
            unit_types.update(TRAIN_INFO.get(structure_type, ()))
        for unit_type in (*build_order_types, *order_pending):
            if not cls._looks_like_structure(bot, unit_type, structure_types):
                unit_types.add(unit_type)

        unit_counts: list[UnitTypeCount] = []
        for unit_type in sorted(unit_types, key=lambda item: item.value):
            existing = unit_existing[unit_type]
            ready = unit_ready[unit_type]
            pending = cls._pending_count(
                bot,
                unit_type,
                structure=False,
                explicit=explicit_unit_pending,
                fallback=max(existing - ready, order_pending[unit_type]),
            )
            if existing or ready or pending or unit_type == worker_type:
                unit_counts.append(
                    UnitTypeCount(
                        unit_type=unit_type,
                        existing=existing,
                        ready=ready,
                        pending=pending,
                    )
                )

        structure_counts: list[UnitTypeCount] = []
        for unit_type in sorted(structure_types, key=lambda item: item.value):
            existing = structure_existing[unit_type]
            ready = structure_ready[unit_type]
            pending = cls._pending_count(
                bot,
                unit_type,
                structure=True,
                explicit=explicit_structure_pending,
                fallback=max(
                    existing - ready,
                    order_pending[unit_type],
                    cls._count(building_counter.get(unit_type, 0)),
                ),
            )
            if existing or ready or pending:
                structure_counts.append(
                    UnitTypeCount(
                        unit_type=unit_type,
                        existing=existing,
                        ready=ready,
                        pending=pending,
                    )
                )

        unit_count_by_type = {item.unit_type: item for item in unit_counts}
        structure_count_by_type = {
            item.unit_type: item for item in structure_counts
        }
        worker_count = unit_count_by_type.get(
            worker_type,
            UnitTypeCount(worker_type)
            if isinstance(worker_type, UnitTypeId)
            else None,
        )
        workers = CountFacts(
            existing=worker_count.existing if worker_count else 0,
            ready=worker_count.ready if worker_count else 0,
            pending=worker_count.pending if worker_count else 0,
        )

        townhall_types = set(_TOWNHALL_TYPES)
        base_type = cls._safe_attr(bot, "base_townhall_type")
        if isinstance(base_type, UnitTypeId):
            townhall_types.add(base_type)
        townhalls = CountFacts(
            existing=sum(
                count.existing
                for unit_type, count in structure_count_by_type.items()
                if unit_type in townhall_types
            ),
            ready=sum(
                count.ready
                for unit_type, count in structure_count_by_type.items()
                if unit_type in townhall_types
            ),
            pending=sum(
                count.pending
                for unit_type, count in structure_count_by_type.items()
                if unit_type in townhall_types
            ),
        )

        producers: list[ProducerFacts] = []
        for unit_type, count in structure_count_by_type.items():
            if unit_type not in TRAIN_INFO:
                continue
            ready_producers = tuple(
                structure
                for structure in own_structures
                if cls._safe_attr(structure, "type_id") == unit_type
                and bool(cls._safe_attr(structure, "is_ready", True))
            )
            idle = 0
            for producer in ready_producers:
                is_idle = cls._safe_attr(producer, "is_idle")
                if is_idle is None:
                    orders = cls._safe_attr(producer, "orders", ())
                    try:
                        is_idle = not bool(tuple(orders or ()))
                    except (RuntimeError, TypeError):
                        is_idle = False
                idle += bool(is_idle)
            producers.append(
                ProducerFacts(
                    unit_type=unit_type,
                    ready=count.ready,
                    idle=idle,
                    busy=max(0, count.ready - idle),
                    pending=count.pending,
                )
            )
        producers.sort(key=lambda item: item.unit_type.value)

        supply_pending_value = cls._safe_attr(bot, "supply_pending")
        if supply_pending_value is None:
            supply_type = cls._safe_attr(bot, "supply_type")
            supply_pending = 0
            if isinstance(supply_type, UnitTypeId):
                supply_pending = max(
                    unit_count_by_type.get(
                        supply_type, UnitTypeCount(supply_type)
                    ).pending,
                    structure_count_by_type.get(
                        supply_type, UnitTypeCount(supply_type)
                    ).pending,
                )
        else:
            supply_pending = cls._count(supply_pending_value)

        ideal_harvesters, assigned_harvesters = cls._harvester_totals(
            bot, own_structures
        )
        runner = cls._safe_attr(bot, "build_order_runner")
        state = cls._safe_attr(bot, "state")
        score = cls._safe_attr(state, "score")
        return EconomyFacts(
            opening_name=str(cls._safe_attr(runner, "chosen_opening", "") or ""),
            opening_completed=bool(
                cls._safe_attr(runner, "build_completed", False)
            ),
            mineral_collection_rate=cls._rate(
                cls._safe_attr(
                    score,
                    "collection_rate_minerals",
                    cls._safe_attr(bot, "collection_rate_minerals", 0.0),
                )
            ),
            vespene_collection_rate=cls._rate(
                cls._safe_attr(
                    score,
                    "collection_rate_vespene",
                    cls._safe_attr(bot, "collection_rate_vespene", 0.0),
                )
            ),
            workers=workers,
            ideal_harvesters=ideal_harvesters,
            assigned_harvesters=assigned_harvesters,
            townhalls=townhalls,
            supply_pending=supply_pending,
            unit_counts=tuple(unit_counts),
            structure_counts=tuple(structure_counts),
            producers=tuple(producers),
        )

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
        raw_own_units = self._items(bot, "units")
        raw_own_structures = self._items(bot, "structures")
        raw_enemy_units = self._items(bot, "enemy_units")
        raw_enemy_structures = self._items(bot, "enemy_structures")
        own_units = tuple(
            self._unit_snapshot(
                bot,
                unit,
                visible_now=True,
                available_for_mission=(
                    unavailable_units is None or int(unit.tag) not in unavailable_units
                ),
            )
            for unit in raw_own_units
        )
        own_structures = tuple(
            self._unit_snapshot(bot, unit, visible_now=True)
            for unit in raw_own_structures
        )
        enemy_units = tuple(
            self._unit_snapshot(bot, unit, visible_now=True)
            for unit in raw_enemy_units
            if not bool(getattr(unit, "is_memory", False))
        )
        enemy_structures = tuple(
            self._unit_snapshot(bot, unit, visible_now=True)
            for unit in raw_enemy_structures
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
            economy=self._economy_facts(
                bot,
                own_units=raw_own_units,
                own_structures=raw_own_structures,
            ),
        )

    @staticmethod
    def build(
        *,
        world: WorldFacts,
    ) -> AttentionSnapshot:
        return AttentionSnapshot(world=world)

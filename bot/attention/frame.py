"""The frame: what the bot perceives this step, before any interpretation.

`observe` reads Ares/python-sc2 once per frame and returns an immutable
`AttentionState`; every later layer reads that state instead of the bot.
The one thing it carries across frames is the opening record
(`bot.attention.opening`), which is still perception: what was seen, and when.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace

import numpy as np
from ares.consts import BuildingSize
from sc2.data import Alliance, Race
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from .map import BASE_SNAP_DISTANCE, MapView, as_point
from .opening import EMPTY, OpeningObservations, OpeningWatch
from .units import (
    MARINE_POWER,
    SPLASH_TARGETS,
    WORKER_TYPES,
    UnitView,
    is_army,
    unit_power,
    unit_view,
)

TERRAN_PRODUCTION = frozenset({UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT})
# Every unit Ares can train directly from Terran army production. Keeping this
# perception-wide avoids making Attention depend on a style or counter catalog.
TERRAN_TRAINABLE = frozenset(
    unit_type for unit_type, producers in UNIT_TRAINED_FROM.items() if producers & TERRAN_PRODUCTION
)
__all__ = [
    "MARINE_POWER",
    "SPLASH_TARGETS",
    "TERRAN_PRODUCTION",
    "TERRAN_TRAINABLE",
    "WORKER_TYPES",
    "AttentionState",
    "BaseView",
    "UnitView",
    "is_army",
    "observe",
    "unit_power",
    "unit_view",
]


@dataclass(frozen=True, slots=True)
class BaseView:
    base_id: str
    position: Point2
    is_main: bool


@dataclass(frozen=True, slots=True)
class AttentionState:
    iteration: int
    time: float
    minerals: int
    vespene: int
    supply_used: float
    supply_cap: float
    workers: int
    opening: str
    opening_done: bool
    own_units: tuple[UnitView, ...]
    own_structures: tuple[UnitView, ...]
    enemy_units: tuple[UnitView, ...]
    enemy_structures: tuple[UnitView, ...]
    bases: tuple[BaseView, ...]
    dead_tags: frozenset[int]
    map: MapView
    # python-sc2 visibility indexed [y, x]; 2 means in vision now. Left out of
    # equality: two frames that perceived the same units are the same frame.
    visibility: np.ndarray | None = field(default=None, compare=False, repr=False)
    # Upgrades researched to completion.
    upgrades: frozenset[UpgradeId] = frozenset()
    # Unit types whose complete Ares tech requirement is ready this frame.
    tech_ready: frozenset[UnitTypeId] = frozenset()
    # Enemy contacts our Sensor Towers pick up outside vision, by position:
    # the game says nothing more about them. In vision they are enemy units.
    radar_blips: tuple[Point2, ...] = ()
    # The race we are playing against; Random until a unit gives it away.
    enemy_race: Race = Race.NoRace
    # What the early game showed of the enemy's opening, and when: the only
    # part of the frame that remembers older frames, because a fact that was
    # observed stays a fact. Empty outside the opening window.
    enemy_opening: OpeningObservations = EMPTY
    # Current free 2x2 construction spots. None means placement data was not
    # supplied; an empty tuple means no sites are available this frame.
    available_tower_sites: tuple[tuple[Point2, tuple[Point2, ...]], ...] | None = None

    def is_visible(self, point: Point2) -> bool:
        grid = self.visibility
        if grid is None:
            return False
        x, y = int(point.x), int(point.y)
        return 0 <= y < grid.shape[0] and 0 <= x < grid.shape[1] and grid[y, x] == 2


def observe(
    bot, iteration: int, map_view: MapView, opening: OpeningWatch | None = None
) -> AttentionState:
    """This frame, as perception left it. `opening` is the record the opening
    is folded into; without one the frame carries an empty record."""

    supply = _supply_lookup(bot)
    roles = _roles(bot)
    runner = getattr(bot, "build_order_runner", None)
    state = bot.state
    perceived = AttentionState(
        iteration=int(iteration),
        time=float(bot.time),
        minerals=int(bot.minerals),
        vespene=int(bot.vespene),
        supply_used=float(bot.supply_used),
        supply_cap=float(bot.supply_cap),
        # The game's count, like Ares' BuildWorkers: a worker inside a gas
        # building is missing from `bot.units` while it is there, so counting
        # the listed ones flickers. Workers in production are not included.
        workers=int(bot.supply_workers),
        opening=str(getattr(runner, "chosen_opening", "") or ""),
        opening_done=bool(getattr(runner, "build_completed", True)),
        own_units=_views(bot.units, supply, roles),
        own_structures=_views(bot.structures, supply, roles),
        enemy_units=_views(_visible(bot.enemy_units), supply),
        enemy_structures=_views(_visible(bot.enemy_structures), supply),
        bases=_bases(bot.townhalls, map_view),
        dead_tags=frozenset(int(tag) for tag in getattr(state, "dead_units", ())),
        map=map_view,
        visibility=getattr(getattr(state, "visibility", None), "data_numpy", None),
        upgrades=frozenset(getattr(state, "upgrades", ())),
        tech_ready=_ready_tech(bot),
        radar_blips=_radar_blips(bot),
        enemy_race=_enemy_race(bot),
        available_tower_sites=_available_tower_sites(bot, map_view),
    )
    if opening is None:
        return perceived
    return replace(perceived, enemy_opening=opening.observe(perceived))


def _available_tower_sites(bot, map_view: MapView):
    """Keep static geometry separate from occupied and reserved build sites."""

    try:
        placements = bot.mediator.get_placements_dict
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return None
    return tuple(
        (
            base,
            tuple(
                point for point in points
                if (info := placements.get(base, {}).get(BuildingSize.TWO_BY_TWO, {}).get(point))
                and info.get("available", False)
                and not info.get("worker_on_route", False)
                and not info.get("custom", False)
            ),
        )
        for base, points in map_view.tower_sites
    )


def _enemy_race(bot) -> Race:
    """The enemy's race. A Random opponent keeps saying Random, so the first
    unit we see of theirs answers it instead."""

    race = getattr(bot, "enemy_race", Race.NoRace)
    if race not in (Race.NoRace, Race.Random):
        return race
    for unit in (*getattr(bot, "enemy_units", ()), *getattr(bot, "enemy_structures", ())):
        try:
            seen = bot.game_data.units[unit.type_id.value].race
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if seen not in (Race.NoRace, Race.Random):
            return seen
    return race


def _radar_blips(bot) -> tuple[Point2, ...]:
    # Read raw: Ares' unit loop leaves python-sc2's `blips` empty and files each
    # one as a NOTAUNIT enemy with tag 0, which its memory then keeps.
    raw = getattr(getattr(bot.state, "observation_raw", None), "units", ())
    return tuple(
        sorted(
            (
                Point2((float(unit.pos.x), float(unit.pos.y)))
                for unit in raw
                if unit.is_blip and unit.alliance == Alliance.Enemy.value
            ),
            key=lambda point: (point.x, point.y),
        )
    )


def _ready_tech(bot) -> frozenset[UnitTypeId]:
    checker = getattr(bot, "tech_ready_for_unit", None)
    if checker is None:
        return frozenset()
    return frozenset(unit_type for unit_type in TERRAN_TRAINABLE if checker(unit_type))


def _views(
    units: Iterable,
    supply: Callable[[UnitTypeId], float],
    roles: Mapping[int, str] | None = None,
) -> tuple[UnitView, ...]:
    return tuple(sorted((unit_view(unit, supply, roles) for unit in units), key=lambda v: v.tag))


def _roles(bot) -> dict[int, str]:
    """Ares' role of every unit that has one, by tag."""

    try:
        by_role = bot.mediator.get_unit_role_dict
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return {}
    return {
        int(tag): str(getattr(role, "name", role)) for role, tags in by_role.items() for tag in tags
    }


def _visible(units: Iterable) -> Iterable:
    """The units this frame shows. Ares lists the enemies it remembers out of
    sight among `enemy_units`, as the snapshot of an older frame, which still
    reads visible; remembering them is Awareness' job."""

    return (
        unit
        for unit in units
        if getattr(unit, "is_visible", True) and not getattr(unit, "is_memory", False)
    )


def _supply_lookup(bot) -> Callable[[UnitTypeId], float]:
    cache: dict[UnitTypeId, float] = {}

    def supply(type_id: UnitTypeId) -> float:
        if type_id not in cache:
            try:
                cache[type_id] = float(bot.calculate_supply_cost(type_id))
            except (AttributeError, KeyError, TypeError):
                cache[type_id] = 0.0
        return cache[type_id]

    return supply


def _bases(townhalls: Iterable, map_view: MapView) -> tuple[BaseView, ...]:
    bases: dict[str, BaseView] = {}
    for townhall in townhalls:
        if townhall.is_flying:
            continue
        position = as_point(townhall.position)
        anchor = min(
            map_view.expansions,
            key=lambda point: (point.distance_to(position), point.x, point.y),
            default=position,
        )
        if anchor.distance_to(position) > BASE_SNAP_DISTANCE:
            anchor = position
        base_id = f"base:{round(anchor.x)}:{round(anchor.y)}"
        bases[base_id] = BaseView(
            base_id=base_id,
            position=anchor,
            is_main=anchor.distance_to(map_view.own_start) <= BASE_SNAP_DISTANCE,
        )
    return tuple(bases[key] for key in sorted(bases))

"""The frame: what the bot perceives this step, before any interpretation.

`observe` reads Ares/python-sc2 once per frame and returns an immutable
`AttentionState`; every later layer reads that state instead of the bot.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from .map import MapView, as_point

WORKER_TYPES = frozenset(
    {UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.MULE}
)
# Neither workers nor structures, and still not an army.
_NOT_ARMY = frozenset(
    {
        UnitTypeId.MULE,
        UnitTypeId.AUTOTURRET,
        UnitTypeId.LARVA,
        UnitTypeId.EGG,
        UnitTypeId.BROODLING,
        UnitTypeId.OVERLORD,
        UnitTypeId.OVERSEER,
        UnitTypeId.CHANGELING,
        UnitTypeId.OBSERVER,
        UnitTypeId.ADEPTPHASESHIFT,
    }
)
# sqrt(dps * hit points) of a Marine: `UnitView.power` is counted in Marines.
MARINE_POWER = math.sqrt(9.8 * 45.0)
# How many targets one shot covers, in full-damage equivalents, against a group
# standing as our bio ball stands. A shot that covers three units is three times
# the damage of the same shot against one, and that is what makes a sieged tank
# line worth crossing or not. Only auto-attacks count: a spell is not a weapon
# the model can price, and `ground_dps`/`air_dps` do not see one either.
#
# The numbers come from each weapon's splash radii against units of the size of
# a Marine, clumped: the Siege Tank's shot does full damage inside 0.47,
# half inside 0.78 and a quarter inside 1.25, which is about two and a half
# Marines' worth of damage on a ball. A unit with no splash is one target.
SPLASH_TARGETS: Mapping[UnitTypeId, float] = {
    UnitTypeId.SIEGETANKSIEGED: 2.5,
    UnitTypeId.WIDOWMINEBURROWED: 2.5,
    UnitTypeId.LIBERATORAG: 2.0,
    UnitTypeId.HELLION: 2.0,
    UnitTypeId.HELLIONTANK: 2.5,
    UnitTypeId.BANELING: 3.0,
    UnitTypeId.COLOSSUS: 2.5,
    UnitTypeId.ARCHON: 2.0,
    UnitTypeId.LURKERMPBURROWED: 2.5,
    # The glaive bounces twice, at a third and a ninth of the damage.
    UnitTypeId.MUTALISK: 1.5,
}
# A townhall this close to an expansion location is that base.
_BASE_SNAP_DISTANCE = 6.0


@dataclass(frozen=True, slots=True)
class UnitView:
    tag: int
    type_id: UnitTypeId
    position: Point2
    # (health + shield) / (max health + max shield)
    health: float
    power: float
    supply: float
    is_flying: bool
    can_attack_ground: bool
    can_attack_air: bool
    is_worker: bool
    is_structure: bool
    is_ready: bool = True
    # The Ares role the unit holds, by name; None without one.
    role: str | None = None
    energy: float = 0.0
    # Cloaked or burrowed, detected or not.
    is_cloaked: bool = False
    # Cloaked or burrowed and not detected: nothing can shoot it.
    is_hidden: bool = False


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

    def is_visible(self, point: Point2) -> bool:
        grid = self.visibility
        if grid is None:
            return False
        x, y = int(point.x), int(point.y)
        return 0 <= y < grid.shape[0] and 0 <= x < grid.shape[1] and grid[y, x] == 2


def unit_power(dps: float, hit_points: float, targets: float = 1.0) -> float:
    """Lanchester-style fighting value, sqrt(dps * targets * hit points), in
    Marines.

    A shot covers at least the target it is aimed at; one that covers more
    deals that much more damage per shot, so splash multiplies the damage the
    unit puts out, not the damage it takes.
    """

    damage = max(0.0, dps) * max(1.0, targets)
    return math.sqrt(damage * max(0.0, hit_points)) / MARINE_POWER


def is_army(unit: UnitView) -> bool:
    return not unit.is_worker and not unit.is_structure and unit.type_id not in _NOT_ARMY


def observe(bot, iteration: int, map_view: MapView) -> AttentionState:
    supply = _supply_lookup(bot)
    roles = _roles(bot)
    runner = getattr(bot, "build_order_runner", None)
    state = bot.state
    return AttentionState(
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
    )


def unit_view(
    unit,
    supply: Callable[[UnitTypeId], float],
    roles: Mapping[int, str] | None = None,
) -> UnitView:
    hit_points = float(unit.health) + float(unit.shield)
    cloaked = bool(getattr(unit, "is_cloaked", False) or getattr(unit, "is_burrowed", False))
    max_hit_points = float(unit.health_max) + float(unit.shield_max)
    return UnitView(
        tag=int(unit.tag),
        type_id=unit.type_id,
        position=as_point(unit.position),
        health=hit_points / max_hit_points if max_hit_points > 0.0 else 0.0,
        power=unit_power(
            max(float(unit.ground_dps), float(unit.air_dps)),
            hit_points,
            SPLASH_TARGETS.get(unit.type_id, 1.0),
        ),
        supply=supply(unit.type_id),
        is_flying=bool(unit.is_flying),
        can_attack_ground=bool(unit.can_attack_ground),
        can_attack_air=bool(unit.can_attack_air),
        is_worker=unit.type_id in WORKER_TYPES,
        is_structure=bool(unit.is_structure),
        is_ready=bool(unit.is_ready),
        role=None if roles is None else roles.get(int(unit.tag)),
        energy=float(getattr(unit, "energy", 0.0) or 0.0),
        is_cloaked=cloaked,
        is_hidden=cloaked and not bool(getattr(unit, "is_revealed", False)),
    )


def _views(
    units: Iterable,
    supply: Callable[[UnitTypeId], float],
    roles: Mapping[int, str] | None = None,
) -> tuple[UnitView, ...]:
    return tuple(
        sorted((unit_view(unit, supply, roles) for unit in units), key=lambda v: v.tag)
    )


def _roles(bot) -> dict[int, str]:
    """Ares' role of every unit that has one, by tag."""

    try:
        by_role = bot.mediator.get_unit_role_dict
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return {}
    return {
        int(tag): str(getattr(role, "name", role))
        for role, tags in by_role.items()
        for tag in tags
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
        if anchor.distance_to(position) > _BASE_SNAP_DISTANCE:
            anchor = position
        base_id = f"base:{round(anchor.x)}:{round(anchor.y)}"
        bases[base_id] = BaseView(
            base_id=base_id,
            position=anchor,
            is_main=anchor.distance_to(map_view.own_start) <= _BASE_SNAP_DISTANCE,
        )
    return tuple(bases[key] for key in sorted(bases))

"""What a unit is, to perception: the immutable view of one unit and the
classification every later layer reads.

`unit_view` freezes a python-sc2 unit into a `UnitView`; `unit_power` prices it
in Marines. Nothing here says whether a unit is dangerous or valuable: that is
Awareness.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from .map import as_point

WORKER_TYPES = frozenset({UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.MULE})
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
# Orders that walk a unit to a point.
_WALKING_ORDERS = frozenset({AbilityId.MOVE, AbilityId.ATTACK, AbilityId.PATROL, AbilityId.SMART})


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
    # The point the unit's first order walks it to -- a move, attack-move,
    # patrol or right click on the ground; None when it is idle or its order
    # targets a unit. Only our own units show their orders.
    moving_to: Point2 | None = None
    # A Barracks, Factory or Starport with a Reactor or Tech Lab attached.
    has_add_on: bool = False


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
        moving_to=_moving_to(unit),
        has_add_on=bool(getattr(unit, "has_add_on", False)),
    )


def _moving_to(unit) -> Point2 | None:
    orders = getattr(unit, "orders", ())
    if not orders:
        return None
    order = orders[0]
    # The generic id: MOVE_MOVE, SCAN_MOVE and the like remap to these.
    if order.ability.id not in _WALKING_ORDERS or not isinstance(order.target, Point2):
        return None
    return as_point(order.target)

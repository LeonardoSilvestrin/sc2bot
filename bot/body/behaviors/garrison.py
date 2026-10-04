"""Garrison: carries out GARRISON -- get into the Bunker at the target.

The Bunker is the nearest of ours to the target within `BUNKER_REACH` that is
ready and has a free slot; a unit already ordered into it is left alone, so
the order is given once. With no such Bunker -- it died, or the units nearer
filled it first -- the unit attack-moves to the target and fights there.
"""

from __future__ import annotations

from collections.abc import Sequence

from ares.behaviors.combat import CombatManeuver
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.ego.planners import Proposal

from .combat import attack_move

# The Bunker stands this close to the target.
BUNKER_REACH = 4.0


def execute(bot, units: Sequence, proposal: Proposal) -> None:
    bunker = find_bunker(bot, proposal.target)
    for unit in units:
        if bunker is None:
            fight = CombatManeuver()
            fight.add(attack_move(unit, proposal.target))
            bot.register_behavior(fight)
        elif not ordered_onto(unit, bunker.tag):
            unit(AbilityId.SMART, bunker)


def find_bunker(bot, target: Point2):
    bunkers = [
        structure
        for structure in bot.structures
        if structure.type_id is UnitTypeId.BUNKER
        and structure.is_ready
        and structure.cargo_left > 0
        and structure.distance_to(target) <= BUNKER_REACH
    ]
    return min(bunkers, key=lambda bunker: (bunker.distance_to(target), bunker.tag), default=None)


def ordered_onto(unit, tag: int) -> bool:
    """Whether one of the unit's orders already targets the unit `tag`."""

    return any(getattr(order, "target", None) == tag for order in getattr(unit, "orders", ()))

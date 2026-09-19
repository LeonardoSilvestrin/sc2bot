"""StructureControl: lowers and raises the supply depots the structure plan
names, and lifts and lands the production structures it relocates.

A lift cancels what the structure is training first, as Ares' own flying
structures do: a busy structure cannot lift. A landing goes to Ares'
`move_structure`, which flies the structure to its site and lands it there.

`keep_clear` runs once, at the start: it takes the sites the planner wants
empty out of Ares' placement, so Ares' macro builds nothing on them.
"""

from __future__ import annotations

from collections.abc import Iterable

from ares.consts import BuildingSize
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2

from bot.ego.planners import StructurePlan


def execute(bot, plan: StructurePlan) -> None:
    lower = set(plan.lower)
    raise_ = set(plan.raise_)
    lift = set(plan.lift)
    land = dict(plan.land)
    for structure in bot.structures:
        if structure.tag in lower:
            structure(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
        elif structure.tag in raise_:
            structure(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
        elif structure.tag in lift:
            structure(AbilityId.CANCEL_QUEUE5)
            structure(AbilityId.LIFT, queue=True)
        elif structure.tag in land:
            bot.mediator.move_structure(
                structure=structure, target=land[structure.tag], should_land=True
            )


def keep_clear(bot, sites: Iterable[Point2]) -> int:
    """Marks `sites` of the main taken in Ares' placement; returns how many."""

    try:
        placements = bot.mediator.get_placements_dict
    except (AttributeError, KeyError, RuntimeError, TypeError):
        return 0
    main = placements.get(bot.start_location, {}).get(BuildingSize.THREE_BY_THREE, {})
    cleared = 0
    for site in sites:
        info = main.get(site)
        if info is not None:
            info["available"] = False
            cleared += 1
    return cleared

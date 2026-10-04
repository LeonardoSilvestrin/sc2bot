"""Fortify: carries out the defense's fortification plan.

Each wanted Bunker goes to Ares' BuildStructure in its site's placement set,
on the free 3x3 spot nearest the point the plan names, and nowhere else: a
Bunker at another base holds nothing. Ares sends one builder at a time and
waits for the Barracks; this waits for the minerals. A Bunker whose garrison
is to walk out unloads it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ares.behaviors.macro import BuildStructure
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from bot.ego.planners import FortificationPlan

BUNKER_COST = 100


@dataclass(frozen=True, slots=True)
class FortifyReport:
    # Structures handed to Ares to build this frame.
    building: tuple[str, ...] = ()
    # Bunkers told to unload, by tag.
    unloaded: tuple[int, ...] = ()


def execute(bot, plan: FortificationPlan) -> FortifyReport:
    building: list[str] = []
    for site in plan.bunkers:
        if bot.minerals < BUNKER_COST:
            break
        bot.register_behavior(
            BuildStructure(
                site.base,
                UnitTypeId.BUNKER,
                closest_to=site.near,
                production=False,
                find_alternative=False,
            )
        )
        building.append(UnitTypeId.BUNKER.name)
    structures = {structure.tag: structure for structure in bot.structures}
    unloaded: list[int] = []
    for tag in plan.unload:
        bunker = structures.get(tag)
        if bunker is not None and bunker.cargo_used > 0:
            bunker(AbilityId.UNLOADALL_BUNKER)
            unloaded.append(tag)
    return FortifyReport(building=tuple(building), unloaded=tuple(unloaded))

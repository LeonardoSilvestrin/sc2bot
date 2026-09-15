"""StructureControl: lowers and raises the supply depots the structure plan names."""

from __future__ import annotations

from sc2.ids.ability_id import AbilityId

from bot.ego.planners import StructurePlan


def execute(bot, plan: StructurePlan) -> None:
    lower = set(plan.lower)
    raise_ = set(plan.raise_)
    for structure in bot.structures:
        if structure.tag in lower:
            structure(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
        elif structure.tag in raise_:
            structure(AbilityId.MORPH_SUPPLYDEPOT_RAISE)

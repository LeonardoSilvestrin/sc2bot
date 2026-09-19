"""Execute Intel's consolidated infrastructure request."""

from ares.behaviors.macro import BuildStructure
from sc2.ids.unit_typeid import UnitTypeId

from bot.ego.planners import IntelPlan

ENGINEERING_BAY_COST = 125


def execute(bot, plan: IntelPlan) -> tuple[str, ...]:
    if plan.engineering_bay and bot.minerals >= ENGINEERING_BAY_COST:
        bot.register_behavior(
            BuildStructure(bot.start_location, UnitTypeId.ENGINEERINGBAY, to_count=1)
        )
        return (UnitTypeId.ENGINEERINGBAY.name,)
    return ()

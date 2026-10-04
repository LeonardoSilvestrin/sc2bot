"""Repair: carries out REPAIR -- an SCV repairs what is damaged at the target.

The worker is taken off its mineral patch and holds the REPAIRING role, which
keeps Ares' mining and building from taking it back; once no proposal holds
it the Engine releases it and it goes back to mining. It repairs the most
damaged of our ready structures and mechanical units within `REPAIR_REACH` of
the target (lowest health first, nearest on a tie), and an order it already
has on that target is not given again. Workers do not repair each other: two
SCVs repairing one another is a loop, not a defense. With nothing damaged it
waits by the target, where the attack is.
"""

from __future__ import annotations

from collections.abc import Sequence

from ares.behaviors.combat.individual import PathUnitToTarget
from ares.consts import UnitRole
from sc2.ids.ability_id import AbilityId

from bot.attention import WORKER_TYPES
from bot.ego.planners import Proposal

from .garrison import ordered_onto

# What stands this close to the target is repaired.
REPAIR_REACH = 6.0
# A repairer this close to the target is waiting at it.
WAIT_AT = 3.0


def execute(bot, units: Sequence, proposal: Proposal) -> None:
    damaged = damaged_near(bot, proposal)
    ground = bot.mediator.get_ground_grid
    for unit in units:
        bot.mediator.remove_worker_from_mineral(worker_tag=unit.tag)
        bot.mediator.assign_role(tag=unit.tag, role=UnitRole.REPAIRING)
        target = next((thing for thing in damaged if thing.tag != unit.tag), None)
        if target is not None:
            if not ordered_onto(unit, target.tag):
                unit(AbilityId.EFFECT_REPAIR, target)
            continue
        bot.register_behavior(
            PathUnitToTarget(
                unit=unit,
                grid=ground,
                target=proposal.target,
                success_at_distance=WAIT_AT,
                sense_danger=False,
            )
        )


def damaged_near(bot, proposal: Proposal) -> list:
    """What there is to repair at the target, most damaged first."""

    things = [
        thing
        for thing in (*bot.structures, *bot.units)
        if thing.type_id not in WORKER_TYPES
        and thing.is_ready
        and getattr(thing, "is_mechanical", False)
        and thing.health_percentage < 1.0
        and thing.distance_to(proposal.target) <= REPAIR_REACH
    ]
    return sorted(
        things,
        key=lambda thing: (thing.health_percentage, thing.distance_to(proposal.target), thing.tag),
    )

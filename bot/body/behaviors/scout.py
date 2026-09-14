"""Scout: carries out SCOUT -- go and look at the target.

A worker is taken off its mineral patch, and the SCOUTING role keeps Ares'
mining and building from taking the unit back. No danger avoidance: to Ares'
grid the enemy's own workers are danger, and a scout that keeps away from
them never sees the mineral line.
"""

from __future__ import annotations

from collections.abc import Sequence

from ares.behaviors.combat.individual import PathUnitToTarget
from ares.consts import UnitRole

from bot.attention import WORKER_TYPES
from bot.ego.planners import Proposal

# A scout this close to its point has reached it.
SCOUT_ARRIVAL = 3.0


def execute(bot, units: Sequence, proposal: Proposal) -> None:
    ground = bot.mediator.get_ground_grid
    air = bot.mediator.get_air_grid
    for unit in units:
        if unit.type_id in WORKER_TYPES:
            bot.mediator.remove_worker_from_mineral(worker_tag=unit.tag)
        bot.mediator.assign_role(tag=unit.tag, role=UnitRole.SCOUTING)
        bot.register_behavior(
            PathUnitToTarget(
                unit=unit,
                grid=air if unit.is_flying else ground,
                target=proposal.target,
                success_at_distance=SCOUT_ARRIVAL,
                sense_danger=False,
            )
        )

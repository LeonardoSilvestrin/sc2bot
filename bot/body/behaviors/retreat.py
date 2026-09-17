"""Retreat: carries out RETREAT -- walk back to the target without fighting.

A granted unit paths to the target and stops within `HOLD_RADIUS`; it does not
attack on the way. A sieged Siege Tank unsieges first.
"""

from __future__ import annotations

from collections.abc import Sequence

from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import PathUnitToTarget, SiegeTankDecision

from bot.ego.planners import Proposal

from .combat import TANKS
from .core_army import HOLD_RADIUS


def execute(bot, units: Sequence, proposal: Proposal) -> None:
    ground = bot.mediator.get_ground_grid
    air = bot.mediator.get_air_grid
    for unit in units:
        retreat = CombatManeuver()
        if unit.type_id in TANKS:
            retreat.add(
                SiegeTankDecision(
                    unit=unit, close_enemy=[], target=proposal.target, force_unsiege=True
                )
            )
        retreat.add(
            PathUnitToTarget(
                unit=unit,
                grid=air if unit.is_flying else ground,
                target=proposal.target,
                success_at_distance=HOLD_RADIUS,
                sense_danger=False,
            )
        )
        bot.register_behavior(retreat)

"""CoreArmy: carries out HOLD -- hold the target and fight whatever comes.

A granted unit walks to the target, not avoiding danger, and stops within
`HOLD_RADIUS`; with an enemy within `ENGAGE_RADIUS` it attack-moves instead.
A Siege Tank stays sieged near the target.
"""

from __future__ import annotations

from collections.abc import Sequence

from ares.behaviors.combat.individual import PathUnitToTarget

from bot.ego.planners import Proposal

from .combat import attack_move, maneuver

# A holding unit stops walking this close to its point and fights what comes.
HOLD_RADIUS = 4.0
# A holding unit with an enemy this close fights its way instead of walking.
ENGAGE_RADIUS = 10.0


def execute(bot, units: Sequence, proposal: Proposal) -> None:
    ground = bot.mediator.get_ground_grid
    air = bot.mediator.get_air_grid
    enemies = list(bot.enemy_units)
    for unit in units:
        hold = maneuver(unit, proposal.target, enemies, stay_sieged=True)
        if any(enemy.distance_to(unit) <= ENGAGE_RADIUS for enemy in enemies):
            hold.add(attack_move(unit, proposal.target))
        else:
            hold.add(
                PathUnitToTarget(
                    unit=unit,
                    grid=air if unit.is_flying else ground,
                    target=proposal.target,
                    success_at_distance=HOLD_RADIUS,
                    sense_danger=False,
                )
            )
        bot.register_behavior(hold)

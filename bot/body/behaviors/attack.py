"""Defense: carries out ATTACK -- fight at the target.

Every granted unit attack-moves to the target; a Siege Tank also decides on
its own when to siege, without holding the spot.
"""

from __future__ import annotations

from collections.abc import Sequence

from bot.ego.planners import Proposal

from .combat import attack_move, maneuver


def execute(bot, units: Sequence, proposal: Proposal) -> None:
    enemies = list(bot.enemy_units)
    for unit in units:
        fight = maneuver(unit, proposal.target, enemies, stay_sieged=False)
        fight.add(attack_move(unit, proposal.target))
        bot.register_behavior(fight)

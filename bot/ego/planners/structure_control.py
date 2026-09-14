"""StructureControl: what our own structures do by themselves.

For now only supply depots: a finished, raised depot goes down while no
visible ground enemy is within `ENEMY_NEAR` of it. Nothing raises one again.
"""

from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId

from bot.attention import AttentionState
from bot.ego.planners import StructurePlan

# A ground enemy this close to a depot keeps it up.
ENEMY_NEAR = 6.5


def plan(attention: AttentionState) -> StructurePlan:
    raised = [
        structure
        for structure in attention.own_structures
        if structure.type_id is UnitTypeId.SUPPLYDEPOT and structure.is_ready
    ]
    ground = [enemy.position for enemy in attention.enemy_units if not enemy.is_flying]
    lower = tuple(
        depot.tag
        for depot in raised
        if all(depot.position.distance_to(enemy) > ENEMY_NEAR for enemy in ground)
    )
    held_up = len(raised) - len(lower)
    if not raised:
        reason = "no_raised_depots"
    elif held_up:
        reason = "enemy_near"
    else:
        reason = "no_enemy_near"
    return StructurePlan(
        lower=lower,
        reason=reason,
        inputs=(
            ("raised", float(len(raised))),
            ("held_up", float(held_up)),
            ("ground_enemies", float(len(ground))),
        ),
    )

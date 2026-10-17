"""Changelings at home: one unit sent to shoot each.

A Changeling has no weapon, so it is no threat incident, and no unit acquires
it by itself: left alone it watches our bases for the rest of the game. Every
Changeling in sight within `CHANGELING_REACH` of one of our bases gets a
proposal for one ground-shooting unit, to attack where it stands; the attack
behavior shoots it on arrival (`bot.body.behaviors.combat.changeling_for`).
The proposal's id follows the Changeling, so the same unit keeps chasing it.
"""

from __future__ import annotations

from ares.consts import CHANGELING_TYPES

from bot.attention import AttentionState
from bot.ego.planners import Command, Domain, Proposal

OWNER = "defense"
# How far from a base a Changeling is ours to clear, as Awareness' base reach.
CHANGELING_REACH = 30.0
# Below the offense, which a Changeling only watches; above MapControl, so a
# unit that only holds ground goes.
CHANGELING_PRIORITY = -0.5


def changeling_proposals(attention: AttentionState) -> tuple[Proposal, ...]:
    proposals: list[Proposal] = []
    for changeling in attention.enemy_units:
        if changeling.type_id not in CHANGELING_TYPES:
            continue
        distance = min(
            (changeling.position.distance_to(base.position) for base in attention.bases),
            default=None,
        )
        if distance is None or distance > CHANGELING_REACH:
            continue
        proposals.append(
            Proposal(
                proposal_id=f"{OWNER}:changeling:{changeling.tag}",
                owner=OWNER,
                priority=CHANGELING_PRIORITY,
                command=Command.ATTACK,
                target=changeling.position,
                reason="changeling_at_home",
                count=1,
                must_attack=Domain.GROUND,
                inputs=(("base_distance", distance),),
            )
        )
    return tuple(proposals)

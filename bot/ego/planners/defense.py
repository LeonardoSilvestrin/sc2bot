"""Defense: one proposal per base under pressure.

Priority is the base's threat, raised by how much Strategy wants defense, so
it is positive exactly while an attacker is in reach -- always above the
CoreArmy fallback. The size asked for covers the pressure with a margin, in
units of our own army's mean power. An attack only in the air asks only for
units that can shoot up.
"""

from __future__ import annotations

import math

from bot.attention import AttentionState, is_army
from bot.awareness import AwarenessState
from bot.ego.planners import Command, Proposal
from bot.ego.strategy import StrategyState

OWNER = "defense"
# Answer an attack with this much more power than it brings.
COVER_MARGIN = 1.5
# An attack whose pressure is at least this share airborne is an air attack.
AIR_ONLY_SHARE = 0.999


def plan(
    attention: AttentionState, awareness: AwarenessState, strategy: StrategyState
) -> tuple[Proposal, ...]:
    army = [unit for unit in attention.own_units if is_army(unit)]
    fighters = [unit.power for unit in army if unit.power > 0.0]
    mean_power = sum(fighters) / len(fighters) if fighters else 1.0
    anti_air = frozenset(unit.type_id for unit in army if unit.can_attack_air)
    proposals: list[Proposal] = []
    for base in awareness.bases:
        if base.pressure <= 0.0 or base.center is None:
            continue
        air_only = base.air_share >= AIR_ONLY_SHARE
        proposals.append(
            Proposal(
                proposal_id=f"{OWNER}:{base.base_id}",
                owner=OWNER,
                priority=base.threat * (0.5 + 0.5 * strategy.defense),
                command=Command.ATTACK,
                target=base.center,
                reason="air_attack_on_base" if air_only else "base_under_pressure",
                count=max(1, math.ceil(COVER_MARGIN * base.pressure / mean_power)),
                unit_types=anti_air if air_only else None,
                inputs=(
                    ("threat", base.threat),
                    ("pressure", base.pressure),
                    ("cover", base.cover),
                    ("balance", base.balance),
                    ("air_share", base.air_share),
                    ("mean_power", mean_power),
                    ("strategy_defense", strategy.defense),
                ),
            )
        )
    return tuple(proposals)

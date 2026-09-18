"""Composition: the army mix to build now, from the style and what was seen.

The style's composition is the prior: what the bot builds before it knows
anything. Each unit of it then takes a value against the enemy army Awareness
believes in (`seen_enemy_types`: power by type, remembered for minutes), and
its share is the prior times that value:

    value(u) = (sum_e power(e) * reach(u, e) * COUNTERS[u][e] + PRIOR_POWER)
               / (sum_e power(e) + PRIOR_POWER)
    share(u) = prior(u) * value(u) / sum_v prior(v) * value(v)

- `reach(u, e)` is physics: 0 when `u` cannot shoot where `e` is (a Hellion at
  a Mutalisk), 1 otherwise. A unit that shoots nothing (a Medivac) is support
  and keeps its prior.
- `COUNTERS[u][e]` is how much better or worse than even `u` trades against
  `e` for its cost: 1 is even, and a pair not in the table is even.
- `PRIOR_POWER` is how much enemy army, in Marines, weighs as much as the
  prior: a few lings seen shift the mix a little, a whole army shifts it a lot.
  There is no threshold: the mix slides as the belief grows and fades.

Stability comes from the belief, which forgets an unseen unit over minutes
(`AwarenessConfig.army_memory`), not from holding the mix.

The mix also says how many of a production structure should carry a Reactor.
A Reactor trains two units at a time; a unit that needs a Tech Lab (Ares' own
tech requirements) trains one at a time and only beside a Tech Lab. With `s_r`
the share of the mix a structure trains without a Tech Lab and `s_t` the share
it trains with one, both kept in step:

    reactor_share = s_r / (s_r + 2 * s_t)

`bench/smoke-mech2` put Reactors on all Factories but one: five reactor
Factories idled with the Hellion share met while the tanks, 35 % of the mix,
waited on two Tech Labs, and the bank passed 2,800 minerals and 1,600 gas.
"""

from __future__ import annotations

from collections.abc import Iterable

from ares.dicts.unit_data import UNIT_DATA
from ares.dicts.unit_tech_requirement import UNIT_TECH_REQUIREMENT
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.ids.unit_typeid import UnitTypeId

from .styles import ArmyStyle

# Enemy army power, in Marines, that weighs as much as the style's prior.
PRIOR_POWER = 20.0

# The Tech Lab of each production structure.
TECHLAB_OF = {
    UnitTypeId.BARRACKS: UnitTypeId.BARRACKSTECHLAB,
    UnitTypeId.FACTORY: UnitTypeId.FACTORYTECHLAB,
    UnitTypeId.STARPORT: UnitTypeId.STARPORTTECHLAB,
}

# What each unit we build can shoot: (ground, air).
REACH: dict[UnitTypeId, tuple[bool, bool]] = {
    UnitTypeId.MARINE: (True, True),
    UnitTypeId.MARAUDER: (True, False),
    UnitTypeId.SIEGETANK: (True, False),
    UnitTypeId.HELLION: (True, False),
    UnitTypeId.CYCLONE: (True, True),
    UnitTypeId.THOR: (True, True),
    UnitTypeId.WIDOWMINE: (True, True),
    UnitTypeId.VIKINGFIGHTER: (False, True),
    UnitTypeId.MEDIVAC: (False, False),
}

# How our unit trades against theirs for its cost; 1 is even. Only what can
# shoot the target is listed (`REACH` zeroes the rest).
COUNTERS: dict[UnitTypeId, dict[UnitTypeId, float]] = {
    UnitTypeId.HELLION: {
        UnitTypeId.ZERGLING: 2.0,
        UnitTypeId.BANELING: 1.2,
        UnitTypeId.QUEEN: 0.6,
        UnitTypeId.ROACH: 0.4,
        UnitTypeId.RAVAGER: 0.5,
        UnitTypeId.HYDRALISK: 0.8,
        UnitTypeId.LURKERMP: 0.3,
        UnitTypeId.ULTRALISK: 0.3,
        UnitTypeId.ZEALOT: 1.6,
        UnitTypeId.ADEPT: 1.2,
        UnitTypeId.STALKER: 0.5,
        UnitTypeId.MARINE: 1.2,
        UnitTypeId.MARAUDER: 0.4,
    },
    UnitTypeId.CYCLONE: {
        UnitTypeId.ZERGLING: 0.6,
        UnitTypeId.ROACH: 1.3,
        UnitTypeId.RAVAGER: 1.3,
        UnitTypeId.HYDRALISK: 1.0,
        UnitTypeId.MUTALISK: 1.5,
        UnitTypeId.CORRUPTOR: 1.2,
        UnitTypeId.BROODLORD: 1.3,
        UnitTypeId.ULTRALISK: 1.2,
        UnitTypeId.STALKER: 1.2,
        UnitTypeId.VOIDRAY: 1.3,
        UnitTypeId.ZEALOT: 0.6,
    },
    UnitTypeId.SIEGETANK: {
        UnitTypeId.ZERGLING: 1.0,
        UnitTypeId.BANELING: 1.5,
        UnitTypeId.ROACH: 1.6,
        UnitTypeId.RAVAGER: 1.0,
        UnitTypeId.HYDRALISK: 1.7,
        UnitTypeId.LURKERMP: 1.6,
        UnitTypeId.ULTRALISK: 0.7,
        UnitTypeId.STALKER: 1.4,
        UnitTypeId.ZEALOT: 0.8,
        UnitTypeId.IMMORTAL: 0.5,
        UnitTypeId.MARINE: 1.5,
        UnitTypeId.SIEGETANK: 1.2,
    },
    UnitTypeId.THOR: {
        UnitTypeId.ZERGLING: 0.5,
        UnitTypeId.BANELING: 0.8,
        UnitTypeId.ROACH: 1.0,
        UnitTypeId.MUTALISK: 2.0,
        UnitTypeId.CORRUPTOR: 1.0,
        UnitTypeId.BROODLORD: 1.8,
        UnitTypeId.ULTRALISK: 1.2,
        UnitTypeId.PHOENIX: 1.8,
        UnitTypeId.ORACLE: 1.5,
        UnitTypeId.BANSHEE: 1.6,
        UnitTypeId.VIKINGFIGHTER: 1.2,
    },
    UnitTypeId.MARINE: {
        UnitTypeId.ZERGLING: 1.0,
        UnitTypeId.BANELING: 0.4,
        UnitTypeId.MUTALISK: 1.6,
        UnitTypeId.ULTRALISK: 0.4,
        UnitTypeId.LURKERMP: 0.5,
        UnitTypeId.COLOSSUS: 0.4,
        UnitTypeId.ARCHON: 0.5,
        UnitTypeId.VOIDRAY: 1.3,
        UnitTypeId.ORACLE: 1.5,
        UnitTypeId.PHOENIX: 1.2,
        UnitTypeId.SIEGETANK: 0.5,
    },
    UnitTypeId.MARAUDER: {
        UnitTypeId.ZERGLING: 0.5,
        UnitTypeId.BANELING: 1.3,
        UnitTypeId.ROACH: 1.6,
        UnitTypeId.RAVAGER: 1.4,
        UnitTypeId.ULTRALISK: 1.4,
        UnitTypeId.STALKER: 1.6,
        UnitTypeId.IMMORTAL: 0.6,
        UnitTypeId.ZEALOT: 0.7,
        UnitTypeId.SIEGETANK: 1.3,
        UnitTypeId.THOR: 1.3,
    },
}


def mix(
    style: ArmyStyle, enemy: Iterable[tuple[UnitTypeId, float]]
) -> tuple[tuple[UnitTypeId, float, int], ...]:
    """The style's composition, reweighted by what each unit is worth against
    `enemy` (power by type); the priorities stay the style's."""

    enemy = tuple((type_id, power) for type_id, power in enemy if power > 0.0)
    total = sum(power for _, power in enemy)
    weights = [
        prior * value(unit_type, enemy, total) for unit_type, prior, _ in style.composition
    ]
    scale = sum(weights)
    if scale <= 0.0:
        return style.composition
    return tuple(
        (unit_type, weight / scale, priority)
        for (unit_type, _, priority), weight in zip(style.composition, weights, strict=True)
    )


def reactor_share(
    mix: Iterable[tuple[UnitTypeId, float, int]], structure: UnitTypeId
) -> float:
    """The share of `structure` that should carry a Reactor to train `mix` in
    step; 0 when it trains nothing of it."""

    reactor = techlab = 0.0
    for unit_type, share, _ in mix:
        if structure not in UNIT_TRAINED_FROM.get(unit_type, ()):
            continue
        if TECHLAB_OF[structure] in UNIT_TECH_REQUIREMENT.get(unit_type, ()):
            techlab += share
        else:
            reactor += share
    if reactor + techlab <= 0.0:
        return 0.0
    return reactor / (reactor + 2.0 * techlab)


def value(
    unit_type: UnitTypeId, enemy: tuple[tuple[UnitTypeId, float], ...], total: float
) -> float:
    ground, air = REACH.get(unit_type, (True, False))
    if not (ground or air):
        return 1.0
    row = COUNTERS.get(unit_type, {})
    earned = sum(
        power * row.get(type_id, 1.0) * (air if _flies(type_id) else ground)
        for type_id, power in enemy
    )
    return (earned + PRIOR_POWER) / (total + PRIOR_POWER)


def _flies(type_id: UnitTypeId) -> bool:
    return bool(UNIT_DATA.get(type_id, {}).get("flying", False))

# bot/sensors/economy_sensor.py
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter

from bot.mind.attention import EconomySnapshot


def derive_economy_snapshot(bot) -> EconomySnapshot:
    """
    Economy intel module:
    - units_ready histogram
    - supply_left / minerals / gas

    Rule: no side-effects.
    """
    units_ready = Counter()
    try:
        for u in bot.units.ready:
            units_ready[u.type_id] += 1
    except Exception:
        # keep module resilient (intel should never crash the whole bot)
        pass

    try:
        supply_left = int(getattr(bot, "supply_left", 0) or 0)
        minerals = int(getattr(bot, "minerals", 0) or 0)
        gas = int(getattr(bot, "vespene", 0) or 0)
    except Exception:
        supply_left, minerals, gas = 0, 0, 0

    return EconomySnapshot(
        units_ready=dict(units_ready),
        supply_left=supply_left,
        minerals=minerals,
        gas=gas,
    )
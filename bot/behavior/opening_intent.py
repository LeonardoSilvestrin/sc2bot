"""Which tactical capabilities the chosen opening deliberately builds toward.

Not strategy: ``bot.strategy.StrategicIntent`` is what the bot wants right
now. This is only the opening's commitment -- a Banshee raid makes sense for
an opening that researches cloak -- read by the behavior that depends on it.
"""

from __future__ import annotations

from typing import Protocol

from bot.world.attention import WorldFacts


class OpeningIntent(Protocol):
    """Small boundary through which tactical planners inspect the opening."""

    def allows(self, capability: str, world: WorldFacts) -> bool:
        ...


class BuildOpeningIntent:
    """Maps the selected opening to tactical capabilities it deliberately uses."""

    _CAPABILITIES_BY_OPENING = {
        "BansheeCloak": frozenset({"banshee_harass"}),
        "BattleMech": frozenset({"banshee_harass"}),
    }

    def allows(self, capability: str, world: WorldFacts) -> bool:
        capabilities = self._CAPABILITIES_BY_OPENING.get(
            world.economy.opening_name, frozenset()
        )
        return capability in capabilities

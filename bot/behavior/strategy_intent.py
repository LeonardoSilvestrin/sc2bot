from __future__ import annotations

from typing import Protocol

from bot.world.attention import WorldFacts


class StrategicIntent(Protocol):
    """Small boundary through which tactical planners inspect build intent."""

    def allows(self, capability: str, world: WorldFacts) -> bool:
        ...


class BuildStrategicIntent:
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

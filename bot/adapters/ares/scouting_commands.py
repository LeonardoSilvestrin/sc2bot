from __future__ import annotations

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2


class AresScoutingCommands:
    """Translate information-gathering actions into python-sc2 commands."""

    _ORBITAL_TYPES = frozenset(
        {UnitTypeId.ORBITALCOMMAND, UnitTypeId.ORBITALCOMMANDFLYING}
    )

    def __init__(self, bot) -> None:
        self._bot = bot

    def scan(self, *, orbital_tag: int, target: Point2) -> bool:
        orbital = self._bot.unit_tag_dict.get(orbital_tag)
        if (
            orbital is None
            or orbital.type_id not in self._ORBITAL_TYPES
            or not bool(getattr(orbital, "is_ready", True))
        ):
            return False

        from ares.behaviors.combat.individual import UseAbility

        return bool(
            UseAbility(
                ability=AbilityId.SCANNERSWEEP_SCAN,
                unit=orbital,
                target=target,
            ).execute(self._bot, self._bot.config, self._bot.mediator)
        )

"""The jobs a generic mission can ask the army for.

A role is a problem statement ("roam and deny", "hold ground"), not a unit
list: it carries the `CapabilityRequirement` any unit filling it is scored
against, and nothing else. It never knows the build -- what is being
produced only changes which units exist to be scored.

Behaviors whose identity *is* a unit -- Banshee harass, Reaper harass, the
scout -- keep asking for that unit and have no role here. Neither does the
fallback owner: "every combat unit nobody more specific is using" is the
absence of a job, not a job (see `UnitRequirement.any_combat_unit`).
"""

from __future__ import annotations

from enum import Enum, auto

from bot.domain import Capability, CapabilityRequirement


class CombatRole(Enum):
    """MOBILE_CONTROL  roams the map, spots and denies, and runs from fights
    SIEGE_ANCHOR    sets up and holds a position against superior numbers
                    (no consumer yet: the BattleMech tank line)
    """

    MOBILE_CONTROL = auto()
    SIEGE_ANCHOR = auto()

    @property
    def requirement(self) -> CapabilityRequirement:
        return ROLE_REQUIREMENTS[self]


ROLE_REQUIREMENTS: dict[CombatRole, CapabilityRequirement] = {
    CombatRole.MOBILE_CONTROL: CapabilityRequirement(
        name=CombatRole.MOBILE_CONTROL.name,
        mobility=1.0,
        anti_ground=0.6,
        anti_air=0.3,
        range=0.3,
        durability=0.3,
        floors=((Capability.MOBILITY, 0.5), (Capability.ANTI_GROUND, 0.4)),
        requires_anti_ground=True,
    ),
    CombatRole.SIEGE_ANCHOR: CapabilityRequirement(
        name=CombatRole.SIEGE_ANCHOR.name,
        mobility=0.2,
        anti_ground=1.0,
        range=1.0,
        siege=1.0,
        splash=0.7,
        durability=0.7,
        floors=((Capability.RANGE, 0.6), (Capability.SIEGE, 0.5)),
        requires_anti_ground=True,
    ),
}

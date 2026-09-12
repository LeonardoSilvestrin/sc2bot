"""Which unit types a composition intends to produce.

A doctrine is production intent, in three tiers:

    core         the backbone the army is built around
    support      bought alongside the core to cover what it lacks
    specialized  bought for a behavior built around that very unit

It never reaches the mission system. A unit on the map is judged by how well
it serves a mission, not by whether the current doctrine would still buy it:
when macro moves from BIO to MECH, surviving Marines keep fighting wherever
they fit, and the army changes only because what is produced from then on is
Hellions, Cyclones and Tanks. There is no transition doctrine to write.

A unit type may belong to several doctrines (the Siege Tank is core to both);
within one it has exactly one tier. Field-only modes (a sieged Tank, a landed
Viking) are not listed: production buys the base unit.
"""

from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId


@dataclass(frozen=True, slots=True)
class CompositionDoctrine:
    name: str
    core: frozenset[UnitTypeId]
    support: frozenset[UnitTypeId] = frozenset()
    specialized: frozenset[UnitTypeId] = frozenset()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if not self.core:
            raise ValueError("a doctrine needs a core")
        tiers = (self.core, self.support, self.specialized)
        if sum(len(tier) for tier in tiers) != len(self.unit_types):
            raise ValueError("a unit type belongs to exactly one doctrine tier")

    @property
    def unit_types(self) -> frozenset[UnitTypeId]:
        return self.core | self.support | self.specialized

    def includes(self, unit_type: UnitTypeId) -> bool:
        return unit_type in self.unit_types


# What the Bio openings converge to. The Banshee is the BansheeCloak
# opener's raider; Vikings are listed so the doctrine reads as Bio's full
# toolbox, though no goal set buys them yet.
BIO = CompositionDoctrine(
    name="bio",
    core=frozenset({UnitTypeId.MARINE, UnitTypeId.MARAUDER, UnitTypeId.SIEGETANK}),
    support=frozenset({UnitTypeId.MEDIVAC, UnitTypeId.VIKINGFIGHTER}),
    specialized=frozenset({UnitTypeId.BANSHEE}),
)

# What the BattleMech opening converges to. Vikings and Thors are listed so
# the doctrine reads as Mech's full toolbox, though no goal set buys them yet.
MECH = CompositionDoctrine(
    name="mech",
    core=frozenset({UnitTypeId.HELLION, UnitTypeId.CYCLONE, UnitTypeId.SIEGETANK}),
    support=frozenset({UnitTypeId.VIKINGFIGHTER, UnitTypeId.THOR}),
    specialized=frozenset({UnitTypeId.BANSHEE}),
)

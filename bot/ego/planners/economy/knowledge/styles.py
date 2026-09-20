"""Army styles: what army the bot builds, chosen once per game.

A style is data, not code: the opening Ares plays (a build of
`terran_builds.yml`), the composition Ares' SpawnController and
ProductionController keep, the upgrades in order, and which production
structure takes add-ons. The economy plan reads whichever style was chosen;
nothing else in the bot asks which one it is.

The choice is a draw among the styles meant for the enemy's race, made in
`on_start`, and announced in the chat. A bench fixes it by name so that each
style is measured on its own.

Bio: a Barracks with a Reactor trains two Marines at a time, and 5 of the 12
Barracks of `bench/7b/001` never got an add-on while the bank grew past 9,900
minerals with supply free. Once the opening is over, and while the posture is
not DEFEND, idle Barracks with no add-on take Reactors up to the share the mix
asks for (`composition.reactor_share`), and Tech Labs for Marauders beyond it.

Mech: Hellions on reactor Factories, Siege Tanks and Cyclones on Tech Lab
Factories, by the same rule. Ares builds the Armory the vehicle upgrades need
on its own.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from random import Random

from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

ANY_RACE = frozenset((Race.Protoss, Race.Terran, Race.Zerg, Race.Random))


@dataclass(frozen=True, slots=True)
class ArmyStyle:
    name: str
    # The build of `terran_builds.yml` Ares plays as the opening.
    opening: str
    # (unit type, proportion, priority): lower priority numbers build first.
    composition: tuple[tuple[UnitTypeId, float, int], ...]
    # Researched in this order once the opening is over.
    upgrades: tuple[UpgradeId, ...]
    # The production structure that takes an add-on when idle and bare.
    addons_on: UnitTypeId
    # The enemy races this style is drawn against.
    against: frozenset[Race]


BIO = ArmyStyle(
    name="bio",
    opening="BioThreeOneOne",
    composition=(
        (UnitTypeId.MARINE, 0.55, 2),
        (UnitTypeId.MARAUDER, 0.2, 1),
        (UnitTypeId.SIEGETANK, 0.15, 0),
        (UnitTypeId.MEDIVAC, 0.1, 1),
    ),
    # Bio research first, then infantry weapons and armor level by level; the
    # tanks' weapons come after the second infantry level.
    upgrades=(
        UpgradeId.STIMPACK,
        UpgradeId.SHIELDWALL,
        UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,
        UpgradeId.PUNISHERGRENADES,
        UpgradeId.TERRANINFANTRYARMORSLEVEL1,
        UpgradeId.TERRANINFANTRYWEAPONSLEVEL2,
        UpgradeId.TERRANINFANTRYARMORSLEVEL2,
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL1,
        UpgradeId.TERRANINFANTRYWEAPONSLEVEL3,
        UpgradeId.TERRANINFANTRYARMORSLEVEL3,
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL2,
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL3,
    ),
    addons_on=UnitTypeId.BARRACKS,
    against=ANY_RACE,
)

MECH = ArmyStyle(
    name="mech",
    opening="MechHellionTank",
    composition=(
        (UnitTypeId.HELLION, 0.39, 2),
        (UnitTypeId.CYCLONE, 0.24, 1),
        (UnitTypeId.SIEGETANK, 0.37, 0),
    ),
    # Weapons first: the Armory it needs is what the armor needs too. Blue
    # flame is researched on a Factory Tech Lab, which the tanks already hold.
    upgrades=(
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL1,
        UpgradeId.HIGHCAPACITYBARRELS,
        UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1,
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL2,
        UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2,
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL3,
        UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3,
    ),
    addons_on=UnitTypeId.FACTORY,
    against=frozenset((Race.Zerg,)),
)

STYLES: dict[str, ArmyStyle] = {style.name: style for style in (BIO, MECH)}

# How a unit type is said in the chat, where its enum name reads badly.
_SPOKEN = {UnitTypeId.SIEGETANK: "Siege Tank"}


def candidates(enemy_race: Race) -> tuple[ArmyStyle, ...]:
    return tuple(style for style in STYLES.values() if enemy_race in style.against)


def choose(enemy_race: Race, rng: Random, forced: str | None = None) -> ArmyStyle:
    """The style named by `forced`, whatever the race; else a draw among the
    styles meant for `enemy_race`."""

    if forced is not None:
        if forced not in STYLES:
            raise ValueError(f"unknown army style {forced!r}; known: {sorted(STYLES)}")
        return STYLES[forced]
    return rng.choice(candidates(enemy_race) or (BIO,))


def announcement(style: ArmyStyle) -> str:
    units = [
        _SPOKEN.get(unit_type, unit_type.name.title()) for unit_type, _, _ in style.composition
    ]
    return f"Going {style.name.upper()} today: {_listed(units)}."


def _listed(items: Iterable[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"

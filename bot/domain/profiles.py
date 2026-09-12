"""The capability profile of every unit type that fights.

Numbers are calibration knobs, deliberately explicit and in one table: they
rank units for allocation, they do not model damage. A type missing here is
not a combat unit -- never a candidate for a capability requirement, never
held by the fallback owner -- so behaviors that want one (Medivacs, workers)
have to ask for it by identity.

Mode variants of one unit share a profile when the mode is a transient
tactical state (a sieged Tank is still the Tank its mission was given), and
get their own when the mode changes what the unit physically is (a landed
Viking cannot shoot air).
"""

from __future__ import annotations

from functools import lru_cache

from sc2.ids.unit_typeid import UnitTypeId

from .capabilities import (
    REJECTED_NO_PROFILE,
    CapabilityRequirement,
    CombatCapabilities,
    Suitability,
)

_SIEGE_TANK = CombatCapabilities(
    mobility=0.30,
    anti_ground=0.90,
    anti_air=0.00,
    range=1.00,
    siege=1.00,
    splash=0.80,
    durability=0.50,
    attacks_ground=True,
    attacks_air=False,
)
_THOR = CombatCapabilities(
    mobility=0.25,
    anti_ground=0.80,
    anti_air=0.80,
    range=0.70,
    siege=0.20,
    splash=0.40,
    durability=1.00,
    attacks_ground=True,
    attacks_air=True,
)

UNIT_PROFILES: dict[UnitTypeId, CombatCapabilities] = {
    # --- Barracks ---------------------------------------------------------
    UnitTypeId.MARINE: CombatCapabilities(
        mobility=0.55,
        anti_ground=0.45,
        anti_air=0.55,
        range=0.45,
        siege=0.00,
        splash=0.00,
        durability=0.15,
        attacks_ground=True,
        attacks_air=True,
    ),
    UnitTypeId.MARAUDER: CombatCapabilities(
        mobility=0.50,
        anti_ground=0.65,
        anti_air=0.00,
        range=0.45,
        siege=0.00,
        splash=0.00,
        durability=0.40,
        attacks_ground=True,
        attacks_air=False,
    ),
    UnitTypeId.REAPER: CombatCapabilities(
        mobility=0.90,
        anti_ground=0.30,
        anti_air=0.00,
        range=0.40,
        siege=0.00,
        splash=0.00,
        durability=0.15,
        attacks_ground=True,
        attacks_air=False,
    ),
    # --- Factory ----------------------------------------------------------
    UnitTypeId.HELLION: CombatCapabilities(
        mobility=1.00,
        anti_ground=0.50,
        anti_air=0.00,
        range=0.40,
        siege=0.00,
        splash=0.50,
        durability=0.25,
        attacks_ground=True,
        attacks_air=False,
    ),
    UnitTypeId.HELLIONTANK: CombatCapabilities(
        mobility=0.45,
        anti_ground=0.60,
        anti_air=0.00,
        range=0.15,
        siege=0.00,
        splash=0.60,
        durability=0.50,
        attacks_ground=True,
        attacks_air=False,
    ),
    UnitTypeId.CYCLONE: CombatCapabilities(
        mobility=0.75,
        anti_ground=0.60,
        anti_air=0.50,
        range=0.70,
        siege=0.00,
        splash=0.00,
        durability=0.45,
        attacks_ground=True,
        attacks_air=True,
    ),
    UnitTypeId.SIEGETANK: _SIEGE_TANK,
    UnitTypeId.SIEGETANKSIEGED: _SIEGE_TANK,
    UnitTypeId.THOR: _THOR,
    UnitTypeId.THORAP: _THOR,
    # --- Starport ---------------------------------------------------------
    UnitTypeId.VIKINGFIGHTER: CombatCapabilities(
        mobility=0.70,
        anti_ground=0.00,
        anti_air=0.80,
        range=0.90,
        siege=0.00,
        splash=0.00,
        durability=0.35,
        attacks_ground=False,
        attacks_air=True,
        is_flying=True,
    ),
    UnitTypeId.VIKINGASSAULT: CombatCapabilities(
        mobility=0.45,
        anti_ground=0.45,
        anti_air=0.00,
        range=0.40,
        siege=0.00,
        splash=0.00,
        durability=0.35,
        attacks_ground=True,
        attacks_air=False,
    ),
    UnitTypeId.BANSHEE: CombatCapabilities(
        mobility=0.80,
        anti_ground=0.75,
        anti_air=0.00,
        range=0.45,
        siege=0.00,
        splash=0.00,
        durability=0.30,
        attacks_ground=True,
        attacks_air=False,
        is_flying=True,
    ),
}

# Every profiled type whose weapons can hit something: the army, whatever
# build produced it.
COMBAT_UNIT_TYPES: frozenset[UnitTypeId] = frozenset(
    unit_type
    for unit_type, profile in UNIT_PROFILES.items()
    if profile.attacks_ground or profile.attacks_air
)


def capabilities_for(unit_type: UnitTypeId) -> CombatCapabilities | None:
    return UNIT_PROFILES.get(unit_type)


def is_combat_unit(unit_type: UnitTypeId) -> bool:
    return unit_type in COMBAT_UNIT_TYPES


@lru_cache(maxsize=512)
def score_unit_for_requirement(
    unit_type: UnitTypeId, requirement: CapabilityRequirement
) -> Suitability:
    """Cached: the allocator asks this for every candidate on every tick,
    and both arguments are immutable."""

    capabilities = capabilities_for(unit_type)
    if capabilities is None:
        return REJECTED_NO_PROFILE
    return requirement.assess(capabilities)

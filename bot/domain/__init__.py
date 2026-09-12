"""Shared domain model: what the game's units are, independent of any decision.

    capabilities.py  CombatCapabilities (one unit type's military profile),
                     CapabilityRequirement (a profile some job wants) and the
                     suitability math matching the two
    profiles.py      UNIT_PROFILES, the per-unit-type capability table, and
                     the combat-unit predicate derived from it

A leaf package: it imports nothing from `bot` and holds no policy. Which job
asks for which requirement (the mission engine's roles), who gets which unit
(the allocator) and what to buy (macro's composition doctrine) are decisions
built on top of it, each in its own layer -- which is why all three can read
it without depending on each other.
"""

from .capabilities import (
    Capability,
    CapabilityRequirement,
    CombatCapabilities,
    Suitability,
)
from .profiles import (
    COMBAT_UNIT_TYPES,
    UNIT_PROFILES,
    capabilities_for,
    is_combat_unit,
    score_unit_for_requirement,
)

__all__ = [
    "COMBAT_UNIT_TYPES",
    "UNIT_PROFILES",
    "Capability",
    "CapabilityRequirement",
    "CombatCapabilities",
    "Suitability",
    "capabilities_for",
    "is_combat_unit",
    "score_unit_for_requirement",
]

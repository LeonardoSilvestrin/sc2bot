from __future__ import annotations

from collections.abc import Mapping

from .config import MacroPlannerConfig
from .profiles import banshee_cloak

MACRO_PROFILES: Mapping[str, MacroPlannerConfig] = {
    "BioThreeOneOne": MacroPlannerConfig(),
    # No sourced structure-timing benchmark exists for this opener yet, so it
    # runs without a ``reference_build`` floor -- the income/overflow scaling
    # in ``MacroPlanner`` still applies on its own.
    "BansheeCloak": MacroPlannerConfig(goals=banshee_cloak(), reference_build=None),
}


def macro_config_for_opening(opening_name: str) -> MacroPlannerConfig:
    """Post-opening convergence goals for the Ares build runner's chosen opening.

    Falls back to the default profile (``bio_three_one_one``) for an unknown
    or not-yet-resolved opening name, so a build added to ``terran_builds.yml``
    without a matching entry here still converges on something reasonable
    rather than raising.
    """

    return MACRO_PROFILES.get(opening_name, MacroPlannerConfig())


__all__ = ["MACRO_PROFILES", "macro_config_for_opening"]

from __future__ import annotations

from typing import Any, Dict

from bot.builds.banshee_hellion_open import PROFILE as BANSHEE_HELLION_OPEN_PROFILE
from bot.builds.default import PROFILE as DEFAULT_PROFILE
from bot.builds.defensive_opening import PROFILE as DEFENSIVE_OPENING_PROFILE


PROFILES_BY_OPENING: Dict[str, Dict[str, Any]] = {
    "Default": DEFAULT_PROFILE,
    "DefensiveOpening": DEFENSIVE_OPENING_PROFILE,
    "BansheeHellionOpen": BANSHEE_HELLION_OPEN_PROFILE,
}

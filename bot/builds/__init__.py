from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from bot.builds.bio_open import PROFILE as BIO_OPEN_PROFILE
from bot.builds.bio_open import STAGED_PROFILES_BY_PHASE as BIO_OPEN_STAGED_BY_PHASE
from bot.builds.mecha_open import PROFILE as MECHA_OPEN_PROFILE
from bot.builds.mecha_open import STAGED_PROFILES_BY_PHASE as MECHA_OPEN_STAGED_BY_PHASE


PROFILES_BY_OPENING: Dict[str, Dict[str, Any]] = {
    "BioOpen": BIO_OPEN_PROFILE,
    "MechaOpen": MECHA_OPEN_PROFILE,
}


STAGED_PROFILES_BY_OPENING: Dict[str, Dict[str, Dict[str, Any]]] = {
    "BioOpen": BIO_OPEN_STAGED_BY_PHASE,
    "MechaOpen": MECHA_OPEN_STAGED_BY_PHASE,
}


_PHASE_KEYS = ("OPENING", "MIDGAME", "LATEGAME")


def _complete_phase_profiles(*, base_profile: Dict[str, Any], staged: Dict[str, Dict[str, Any]] | None) -> Dict[str, Dict[str, Any]]:
    stage = dict(staged or {})
    out: Dict[str, Dict[str, Any]] = {}
    for phase in _PHASE_KEYS:
        phase_profile = stage.get(phase)
        if not isinstance(phase_profile, dict):
            out[phase] = deepcopy(dict(base_profile))
        else:
            out[phase] = deepcopy(dict(phase_profile))
    return out


STAGED_PROFILES_BY_OPENING = {
    opening: _complete_phase_profiles(
        base_profile=dict(profile),
        staged=STAGED_PROFILES_BY_OPENING.get(opening),
    )
    for opening, profile in PROFILES_BY_OPENING.items()
}

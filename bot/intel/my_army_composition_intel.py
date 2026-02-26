# =============================================================================
# bot/intel/my_army_composition_intel.py  (NEW)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from bot.mind.awareness import Awareness, K
from bot.mind.attention import Attention


@dataclass(frozen=True)
class MyArmyCompositionConfig:
    """
    Strategy-level macro reference:
      - desired mode (discrete)
      - desired comp (ratios)
    This is NOT production/spending. It's the setpoint.

    Keep TTL short: consumers should treat it as "recent intent".
    """
    ttl_s: float = 25.0
    min_confidence: float = 0.55

    # Default comps (ratios sum ~= 1.0)
    comp_defensive: Dict[str, float] = None
    comp_standard: Dict[str, float] = None
    comp_punish: Dict[str, float] = None

    def __post_init__(self):
        object.__setattr__(
            self,
            "comp_defensive",
            self.comp_defensive
            or {
                "MARINE": 0.75,
                "MARAUDER": 0.20,
                "MEDIVAC": 0.05,
            },
        )
        object.__setattr__(
            self,
            "comp_standard",
            self.comp_standard
            or {
                "MARINE": 0.60,
                "MARAUDER": 0.25,
                "MEDIVAC": 0.15,
            },
        )
        object.__setattr__(
            self,
            "comp_punish",
            self.comp_punish
            or {
                "MARINE": 0.65,
                "MARAUDER": 0.15,
                "MEDIVAC": 0.20,
            },
        )


def _normalize(comp: Dict[str, float]) -> Dict[str, float]:
    try:
        total = float(sum(float(v) for v in comp.values()))
    except Exception:
        return dict(comp)
    if total <= 0:
        return dict(comp)
    return {str(k): float(v) / total for k, v in comp.items()}


def derive_my_army_composition_intel(
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    cfg: MyArmyCompositionConfig = MyArmyCompositionConfig(),
) -> None:
    """
    Reads enemy opening belief from Awareness, emits desired mode+comp into Awareness.

    Writes:
      - macro:desired:mode
      - macro:desired:comp
      - macro:desired:last_update_t
    """
    enemy_kind = awareness.mem.get(K("enemy", "opening", "kind"), now=now, default="NORMAL")
    conf = awareness.mem.get(K("enemy", "opening", "confidence"), now=now, default=0.0)

    mode = "STANDARD"
    if float(conf) >= float(cfg.min_confidence):
        if str(enemy_kind) == "AGGRESSIVE":
            mode = "DEFENSIVE"
        elif str(enemy_kind) == "GREEDY":
            mode = "PUNISH"
        else:
            mode = "STANDARD"

    if mode == "DEFENSIVE":
        comp = _normalize(dict(cfg.comp_defensive))
    elif mode == "PUNISH":
        comp = _normalize(dict(cfg.comp_punish))
    else:
        comp = _normalize(dict(cfg.comp_standard))

    awareness.mem.set(K("macro", "desired", "mode"), value=str(mode), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "comp"), value=dict(comp), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("macro", "desired", "last_update_t"), value=float(now), now=now, ttl=None)

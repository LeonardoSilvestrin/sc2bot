"""Offense: take the army to the enemy once waiting gains nothing more.

- `planner.OffensePlanner`: whether to attack, the cooldown, when to ask an
  attack to end.
- `missions.main_attack.MainAttackMission`: how the attack goes -- gathering,
  advancing, fighting, searching, retreating and regrouping.
"""

from .missions.main_attack import (
    ENEMY_START,
    FLYING_STRUCTURE,
    KIND,
    KNOWN_BASE,
    KNOWN_STRUCTURE,
    OWNER,
    PRIORITY,
    SEARCH_TARGET,
    LocalFight,
    MainAttackMission,
    OffenseConfig,
    Stage,
)
from .planner import OffensePlan, OffensePlanner

__all__ = [
    "ENEMY_START",
    "FLYING_STRUCTURE",
    "KIND",
    "KNOWN_BASE",
    "KNOWN_STRUCTURE",
    "OWNER",
    "PRIORITY",
    "SEARCH_TARGET",
    "LocalFight",
    "MainAttackMission",
    "OffenseConfig",
    "OffensePlan",
    "OffensePlanner",
    "Stage",
]

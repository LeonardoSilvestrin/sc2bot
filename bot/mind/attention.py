# bot/mind/attention.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.inteligence.threat import Threat, ThreatReport
from bot.mind.awareness import Awareness


@dataclass(frozen=True)
class Attention:
    """
    Tick snapshot (read-only).
    - immutable
    - derived each tick
    - should NOT carry history; history belongs in Awareness
    """

    opening_done: bool

    threatened: bool
    defense_urgency: int  # 0..100
    threat_pos: Optional[Point2] = None
    enemy_count_near_bases: int = 0

    orbital_ready_to_scan: bool = False
    orbital_energy: float = 0.0

    time: float = 0.0


def _orbital_scan_status(bot) -> Tuple[bool, float]:
    try:
        orbitals = bot.structures(U.ORBITALCOMMAND).ready
        if orbitals.amount == 0:
            return False, 0.0
        oc = orbitals.first
        energy = float(getattr(oc, "energy", 0.0) or 0.0)
        return (energy >= 50.0), energy
    except Exception:
        return False, 0.0


def derive_attention(bot, *, awareness: Awareness, threat: Threat) -> Attention:
    """
    Derive tick snapshot. Rule: no side-effects (do not write awareness).
    """
    opening_done = bool(getattr(bot, "build_order_runner", None) and bot.build_order_runner.build_completed)

    thr: ThreatReport = threat.evaluate(bot)
    orbital_ready, orbital_energy = _orbital_scan_status(bot)

    return Attention(
        opening_done=opening_done,
        threatened=bool(thr.threatened),
        defense_urgency=int(thr.urgency),
        threat_pos=thr.threat_pos,
        enemy_count_near_bases=int(thr.enemy_count),
        orbital_ready_to_scan=bool(orbital_ready),
        orbital_energy=float(orbital_energy),
        time=float(getattr(bot, "time", 0.0)),
    )
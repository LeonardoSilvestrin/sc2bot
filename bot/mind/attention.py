# bot/mind/attention.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
from collections import Counter

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.intel.threat_intel import Threat, ThreatReport
from bot.mind.awareness import Awareness


@dataclass(frozen=True)
class EconomySnapshot:
    units_ready: dict
    supply_left: int
    minerals: int
    gas: int


@dataclass(frozen=True)
class CombatSnapshot:
    threatened: bool
    defense_urgency: int
    threat_pos: Optional[Point2]
    enemy_count_near_bases: int


@dataclass(frozen=True)
class IntelSnapshot:
    orbital_ready_to_scan: bool
    orbital_energy: float


@dataclass(frozen=True)
class MacroSnapshot:
    opening_done: bool


@dataclass(frozen=True)
class Attention:
    """
    Tick snapshot (read-only).
    - immutable
    - derived each tick
    - history belongs in Awareness
    """
    economy: EconomySnapshot
    combat: CombatSnapshot
    intel: IntelSnapshot
    macro: MacroSnapshot
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


def _opening_done(bot) -> bool:
    # (1) Ares build order runner
    bor = getattr(bot, "build_order_runner", None)
    if bor is not None:
        try:
            if bool(getattr(bor, "build_completed", False)):
                return True
        except Exception:
            pass

    # time fallback
    try:
        now = float(getattr(bot, "time", 0.0) or 0.0)
    except Exception:
        now = 0.0

    # (2) Milestones
    try:
        if bot.structures(U.FACTORY).ready.amount > 0:
            return True
        if bot.structures(U.STARPORT).ready.amount > 0:
            return True
        if bot.townhalls.ready.amount >= 2:
            return True
    except Exception:
        pass

    # (3) Hard fallback
    return now >= 180.0


def derive_attention(bot, *, awareness: Awareness, threat: Threat) -> Attention:
    """
    Derive tick snapshot.
    Rule: no side-effects.
    """
    thr: ThreatReport = threat.evaluate(bot)
    orbital_ready, orbital_energy = _orbital_scan_status(bot)

    units_ready = Counter()
    try:
        for u in bot.units.ready:
            units_ready[u.type_id] += 1
    except Exception:
        pass

    economy = EconomySnapshot(
        units_ready=dict(units_ready),
        supply_left=int(getattr(bot, "supply_left", 0) or 0),
        minerals=int(getattr(bot, "minerals", 0) or 0),
        gas=int(getattr(bot, "vespene", 0) or 0),
    )

    combat = CombatSnapshot(
        threatened=bool(thr.threatened),
        defense_urgency=int(thr.urgency),
        threat_pos=thr.threat_pos,
        enemy_count_near_bases=int(thr.enemy_count),
    )

    intel = IntelSnapshot(
        orbital_ready_to_scan=bool(orbital_ready),
        orbital_energy=float(orbital_energy),
    )

    macro = MacroSnapshot(
        opening_done=bool(_opening_done(bot)),
    )

    return Attention(
        economy=economy,
        combat=combat,
        intel=intel,
        macro=macro,
        time=float(getattr(bot, "time", 0.0)),
    )
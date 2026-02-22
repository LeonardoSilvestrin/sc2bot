#api.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import inspect

from sc2.ids.unit_typeid import UnitTypeId as U


def _is_awaitable(x: Any) -> bool:
    try:
        return inspect.isawaitable(x)
    except Exception:
        return False


async def _maybe_await(x: Any) -> Any:
    if _is_awaitable(x):
        return await x
    return x


@dataclass(frozen=True)
class Snapshot:
    t: float
    it: int
    m: int
    g: int
    supply_used: int
    supply_cap: int
    supply_left: int


class BotAPI:
    """
    Adapter para lidar com diferenças de forks:
    - bot.units vs bot.structures
    - .ready/.idle/.exists/.amount vs listas simples
    - bot.do / distribute_workers sync ou async
    - already_pending pode existir ou não
    """

    def __init__(self, bot: Any):
        self.bot = bot

    # ---------------------------
    # Snapshot
    # ---------------------------
    def snapshot(self) -> Snapshot:
        t = float(getattr(self.bot, "time", 0.0) or 0.0)
        it = int(getattr(self.bot, "iteration", 0) or 0)
        m = int(getattr(self.bot, "minerals", 0) or 0)
        g = int(getattr(self.bot, "vespene", 0) or 0)
        su = int(getattr(self.bot, "supply_used", 0) or 0)
        sc = int(getattr(self.bot, "supply_cap", 0) or 0)
        sl = int(getattr(self.bot, "supply_left", 0) or 0)
        return Snapshot(t=t, it=it, m=m, g=g, supply_used=su, supply_cap=sc, supply_left=sl)

    # ---------------------------
    # Unit queries
    # ---------------------------
    def units(self, unit_type: U):
        if hasattr(self.bot, "units"):
            try:
                return self.bot.units(unit_type)
            except Exception:
                pass
        if hasattr(self.bot, "structures"):
            try:
                return self.bot.structures(unit_type)
            except Exception:
                pass
        return []

    def ready(self, unit_type: U):
        us = self.units(unit_type)
        if hasattr(us, "ready"):
            return us.ready
        return [u for u in us if getattr(u, "is_ready", False)]

    def idle(self, units):
        if hasattr(units, "idle"):
            return units.idle
        return [u for u in units if getattr(u, "is_idle", False)]

    def exists(self, units) -> bool:
        if units is None:
            return False
        if hasattr(units, "exists"):
            return bool(units.exists)
        try:
            return len(units) > 0
        except Exception:
            return False

    def amount(self, units) -> int:
        if units is None:
            return 0
        if hasattr(units, "amount"):
            return int(units.amount)
        try:
            return len(units)
        except Exception:
            return 0

    def first(self, units):
        if units is None:
            return None
        if hasattr(units, "first"):
            return units.first
        try:
            return units[0] if len(units) else None
        except Exception:
            return None

    def closest_to(self, units, pos):
        if units is None:
            return None
        if hasattr(units, "closest_to"):
            try:
                return units.closest_to(pos)
            except Exception:
                pass
        best = None
        best_d = 1e18
        try:
            for u in units:
                p = getattr(u, "position", None)
                if p is None:
                    continue
                d = p.distance_to(pos)
                if d < best_d:
                    best_d = d
                    best = u
        except Exception:
            return None
        return best

    def closer_than(self, units, dist: float, pos):
        if units is None:
            return []
        if hasattr(units, "closer_than"):
            try:
                return units.closer_than(dist, pos)
            except Exception:
                pass
        out = []
        try:
            for u in units:
                p = getattr(u, "position", None)
                if p is None:
                    continue
                if p.distance_to(pos) < dist:
                    out.append(u)
        except Exception:
            return []
        return out

    # ---------------------------
    # Economy helpers
    # ---------------------------
    def already_pending(self, unit_type: U) -> int:
        fn = getattr(self.bot, "already_pending", None)
        if callable(fn):
            try:
                return int(fn(unit_type))
            except Exception:
                return 0
        return 0

    def can_afford(self, unit_type: U) -> bool:
        fn = getattr(self.bot, "can_afford", None)
        if callable(fn):
            try:
                return bool(fn(unit_type))
            except Exception:
                pass
        # Fallback: check raw resources
        m = int(getattr(self.bot, "minerals", 0)) or 0
        g = int(getattr(self.bot, "vespene", 0)) or 0
        calc = getattr(self.bot, "calculate_cost", None)
        if callable(calc):
            try:
                c = calc(unit_type)
                cm = int(getattr(c, "minerals", 0)) or 0
                cg = int(getattr(c, "vespene", 0)) or 0
                return m >= cm and g >= cg
            except Exception:
                pass
        return False

    # ---------------------------
    # Commands (sync/async safe)
    # ---------------------------
    async def do(self, cmd) -> Any:
        fn = getattr(self.bot, "do", None)
        if not callable(fn):
            return None
        try:
            return await _maybe_await(fn(cmd))
        except Exception:
            # do not swallow silently here; caller logs failures
            raise

    async def distribute_workers(self) -> Any:
        fn = getattr(self.bot, "distribute_workers", None)
        if not callable(fn):
            return None
        return await _maybe_await(fn())
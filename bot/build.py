#build.py
from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from .api import BotAPI
from .utils import snap


class Builder:
    def __init__(self, bot, econ, placement, state, debug: bool = True):
        self.bot = bot
        self.api = BotAPI(bot)
        self.econ = econ
        self.place = placement
        self.state = state
        self.debug = debug

    def _has_dbg(self) -> bool:
        return hasattr(self.bot, "dbg") and self.bot.dbg is not None

    def _log(self, channel: str, payload: dict) -> None:
        if not self._has_dbg():
            return
        try:
            snap0 = self.api.snapshot()
            payload.setdefault("t", snap0.t)
            payload.setdefault("it", snap0.it)

            dbg = self.bot.dbg
            fn = getattr(dbg, "log_action", None)
            if channel == "building":
                fn = getattr(dbg, "log_building", None) or fn
            elif channel == "placement":
                fn = getattr(dbg, "log_placement", None) or fn

            if callable(fn):
                fn(payload)
        except Exception:
            return

    async def try_build(self, key: str, unit_type: U, desired: Point2, cooldown: int = 16, max_existing: int | None = 0) -> bool:
        it = self.api.snapshot().it

        # cooldown anti-spam
        if (it - self.state.last_try.get(key, -999999)) < cooldown:
            return False
        self.state.last_try[key] = it

        # anti-spam: control maximum existing instances allowed
        # Default: max_existing=0 (previous behavior) -> if any exist, skip
        existing_count = self.api.amount(self.api.units(unit_type))
        if max_existing is not None:
            if existing_count > max_existing:
                return False
        # pending still blocks to avoid duplicate orders in-flight
        if self.api.already_pending(unit_type) > 0:
            return False

        # economy (considera reservas)
        if not self.econ.can_afford_reserved(unit_type):
            return False

        desired = snap(desired)

        # pick worker (prefer idle -> gathering -> closest)
        workers = getattr(self.bot, "workers", None)
        if workers is None:
            return False
        
        # Check if workers collection has any units (use api helper)
        if not self.api.exists(workers):
            return False

        try:
            idle = getattr(workers, "idle", None)
            if idle is not None and getattr(idle, "exists", False):
                worker = self.api.closest_to(idle, desired)
            else:
                worker = None
        except Exception:
            worker = None

        if worker is None:
            try:
                gathering = getattr(workers, "gathering", None)
                if gathering is not None and getattr(gathering, "exists", False):
                    worker = self.api.closest_to(gathering, desired)
            except Exception:
                worker = None

        if worker is None:
            worker = self.api.closest_to(workers, desired)

        if worker is None:
            return False

        # placement - try the desired position first, fall back to ring search if needed
        if unit_type == U.REFINERY:
            pos = self.place.find_refinery_spot(desired)
            if pos is None:
                self._log("building", {
                    "event": "build_skip",
                    "name": key,
                    "unit": str(unit_type),
                    "reason": "no_geyser_near",
                    "desired": [int(desired.x), int(desired.y)],
                })
                return False
            strict_flag = True
        else:
            # For non-refinery buildings: try desired position, then ring search
            snap_desired = snap(desired)
            result = await self.place.find_position(unit_type, snap_desired, max_dist=20)
            if result is None:
                self._log("building", {
                    "event": "build_skip",
                    "name": key,
                    "unit": str(unit_type),
                    "reason": "no_valid_position",
                    "desired": [int(snap_desired.x), int(snap_desired.y)],
                })
                return False
            pos = result.pos
            strict_flag = result.strict

        snap0 = self.api.snapshot()
        self._log("building", {
            "event": "build_attempt",
            "name": key,
            "unit": str(unit_type),
            "desired": [int(desired.x), int(desired.y)],
            "pos": [int(pos.x), int(pos.y)],
            "strict": strict_flag,
            "m": snap0.m,
            "g": snap0.g,
        })

        # reserve after we commit to attempt
        self.econ.reserve(unit_type)

        # execute
        try:
            if hasattr(self.bot, "build"):
                try:
                    await self.bot.build(unit_type, near=pos)
                except TypeError:
                    await self.bot.build(unit_type, pos)

                self._log("building", {
                    "event": "build_issued",
                    "name": key,
                    "unit": str(unit_type),
                    "pos": [int(pos.x), int(pos.y)],
                    "ok": True,
                })
                return True

            cmd = worker.build(unit_type, pos)
            ok = await self.api.do(cmd)
            self._log("building", {
                "event": "build_issued",
                "name": key,
                "unit": str(unit_type),
                "pos": [int(pos.x), int(pos.y)],
                "ok": bool(ok),
                "via": "worker.build",
            })
            return bool(ok)

        except Exception as e:
            self._log("building", {
                "event": "build_fail",
                "name": key,
                "unit": str(unit_type),
                "pos": [int(pos.x), int(pos.y)],
                "exc_type": type(e).__name__,
                "exc": str(e),
            })
            return False
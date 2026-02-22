#orchestrator.py
from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from .api import BotAPI
from .state import BotState
from .economy import Economy
from .placement import Placement
from .build import Builder
from .drop import Drop
from .utils import snap


class Orchestrator:
    def __init__(self, bot, debug: bool = True):
        self.bot = bot
        self.api = BotAPI(bot)
        self.debug = debug

        self.state = BotState()
        self.econ = Economy(bot)
        self.place = Placement(bot, debug=debug)
        self.builder = Builder(bot, self.econ, self.place, self.state, debug=debug)
        self.drop = Drop(bot, self.state, debug=debug)

        # knobs
        self.scv_target = 20
        self.depot_trigger_supply_left = 4

        # tech goals for drop
        self.marines_for_drop = 8
        self.need_factory = True
        self.need_starport = True

        # throttles
        self._last_intent_it: dict[str, int] = {}

    # =============================================================================
    # Debug helpers (throttled)
    # =============================================================================
    def _has_dbg(self) -> bool:
        return hasattr(self.bot, "dbg") and self.bot.dbg is not None

    def _log(self, channel: str, payload: dict) -> None:
        if not self._has_dbg():
            return
        try:
            # add t/it if available, but don't override if caller already set
            snap0 = self.api.snapshot()
            payload.setdefault("t", snap0.t)
            payload.setdefault("it", snap0.it)

            # route to dbg.<log_*>
            dbg = self.bot.dbg
            fn = None
            if channel == "action":
                fn = getattr(dbg, "log_action", None)
            elif channel == "state":
                fn = getattr(dbg, "log_state", None)
            elif channel == "placement":
                fn = getattr(dbg, "log_placement", None)
            elif channel == "building":
                fn = getattr(dbg, "log_building", None)
            else:
                fn = getattr(dbg, "log_action", None)

            if callable(fn):
                fn(payload)
        except Exception:
            # logging must never break gameplay
            return

    def _emit_intent(self, key: str, payload: dict, *, every_n_it: int = 10) -> None:
        """
        Evita spammar a mesma intenção todo frame.
        """
        it = self.api.snapshot().it
        last = self._last_intent_it.get(key, -10**9)
        if it - last < every_n_it:
            return
        self._last_intent_it[key] = it
        self._log("action", payload)

    # =============================================================================
    # CC principal
    # =============================================================================
    def _main_cc(self):
        th = getattr(self.bot, "townhalls", None)
        if th is not None:
            th_ready = th.ready if hasattr(th, "ready") else [u for u in th if getattr(u, "is_ready", False)]
            if self.api.exists(th_ready):
                return self.api.first(th_ready)

        for t in (U.ORBITALCOMMAND, U.PLANETARYFORTRESS, U.COMMANDCENTER):
            ready = self.api.ready(t)
            if self.api.exists(ready):
                return self.api.first(ready)

        return None

    # =============================================================================
    # RESERVA / PRIORIDADES
    # =============================================================================
    def _need_depot(self) -> bool:
        # Count existing + pending depots
        existing_depots = self.api.amount(self.api.units(U.SUPPLYDEPOT))
        pending_depots = self.api.already_pending(U.SUPPLYDEPOT)
        total_depots = existing_depots + pending_depots
        
        supply_left = int(getattr(self.bot, "supply_left", 0) or 0)
        
        # Allow more depots if supply is low and none are pending
        if supply_left <= self.depot_trigger_supply_left and pending_depots == 0:
            return True
        
        return False

    def _need_rax(self) -> bool:
        if not self.api.exists(self.api.ready(U.SUPPLYDEPOT)):
            return False
        return not self.api.exists(self.api.units(U.BARRACKS))

    def _need_refinery(self) -> bool:
        # Refinery can start once barracks exists (even if still building), not just when ready
        if not self.api.exists(self.api.units(U.BARRACKS)):
            return False
        # Check if refinery already exists or is pending
        existing_refinery = self.api.amount(self.api.units(U.REFINERY))
        pending_refinery = self.api.already_pending(U.REFINERY)
        return (existing_refinery + pending_refinery) == 0

    def _need_factory(self) -> bool:
        return (
            self.state.build.ref_started
            and not self.state.build.factory_started
            and self.need_factory
        )

    def _need_starport(self) -> bool:
        return (
            self.state.build.factory_started
            and not self.state.build.starport_started
            and self.need_starport
        )

    def _reserve_critical(self) -> None:
        if self._need_depot():
            self.econ.reserve(U.SUPPLYDEPOT)
            return
        if self._need_rax():
            self.econ.reserve(U.BARRACKS)
            return
        if self._need_refinery():
            self.econ.reserve(U.REFINERY)
            return
        if self._need_factory():
            self.econ.reserve(U.FACTORY)
            return
        if self._need_starport():
            self.econ.reserve(U.STARPORT)
            return

    # =============================================================================
    # MACRO: WORKERS
    # =============================================================================
    async def _macro_workers(self, cc) -> None:
        workers = getattr(self.bot, "workers", None)
        if workers is None:
            return
        if self.api.amount(workers) >= self.scv_target:
            return

        # Only block SCV if supply is actually capped (0 left), not just "low"
        # This prevents deadlock where bot can't train SCV to build depot to get supply
        supply_left = int(getattr(self.bot, "supply_left", 0) or 0)
        if supply_left <= 0:
            self._emit_intent(
                "intent_scv_blocked",
                {
                    "event": "intent",
                    "what": "train",
                    "unit": "SCV",
                    "reason": "supply_capped",
                },
                every_n_it=25,
            )
            return

        if getattr(cc, "is_idle", False) and self.api.can_afford(U.SCV) and supply_left > 0:
            self._log("action", {"event": "do", "what": "train", "unit": "SCV"})
            await self.bot.do(cc.train(U.SCV))

    # =============================================================================
    # MACRO: DEPOT / RAX
    # =============================================================================
    async def _macro_depot(self, cc) -> None:
        if not self._need_depot():
            return

        desired = snap(cc.position.towards(self.bot.game_info.map_center, 6))
        self._emit_intent(
            "intent_depot",
            {
                "event": "intent",
                "what": "build",
                "unit": str(U.SUPPLYDEPOT),
                "desired": [int(desired.x), int(desired.y)],
                "reason": "supply_low",
            },
            every_n_it=10,
        )

        ok = await self.builder.try_build("depot", U.SUPPLYDEPOT, desired, cooldown=10)
        self._log(
            "building",
            {
                "event": "build_result",
                "name": "depot",
                "unit": str(U.SUPPLYDEPOT),
                "desired": [int(desired.x), int(desired.y)],
                "ok": bool(ok),
            },
        )

    async def _macro_rax(self, cc) -> None:
        if not self._need_rax():
            return

        near = snap(cc.position.towards(self.bot.game_info.map_center, 10))
        self._emit_intent(
            "intent_rax",
            {
                "event": "intent",
                "what": "build",
                "unit": str(U.BARRACKS),
                "near": [int(near.x), int(near.y)],
                "reason": "after_depot",
            },
            every_n_it=10,
        )

        ramp = getattr(self.bot, "main_base_ramp", None)
        ramp_pos = getattr(ramp, "barracks_correct_placement", None) if ramp is not None else None
        if ramp_pos is not None:
            desired = snap(ramp_pos)
            self._log(
                "placement",
                {
                    "event": "placement_hint",
                    "unit": str(U.BARRACKS),
                    "source": "ramp.barracks_correct_placement",
                    "pos": [int(desired.x), int(desired.y)],
                },
            )
            pr = await self.place.can_place_strict(U.BARRACKS, desired)
            can_place, strict = bool(pr[0]), bool(pr[1])
            self._log(
                "placement",
                {
                    "event": "can_place",
                    "unit": str(U.BARRACKS),
                    "pos": [int(desired.x), int(desired.y)],
                    "ok": can_place,
                    "strict": strict,
                },
            )
            if not can_place:
                desired = None
        else:
            desired = None

        if desired is None:
            found = await self.place.find_near(U.BARRACKS, near, max_dist=25)
            if found is None:
                self._log(
                    "placement",
                    {
                        "event": "placement_fail",
                        "unit": str(U.BARRACKS),
                        "near": [int(near.x), int(near.y)],
                        "max_dist": 25,
                    },
                )
                return
            desired = found.pos
            self._log(
                "placement",
                {
                    "event": "placement_ok",
                    "unit": str(U.BARRACKS),
                    "pos": [int(desired.x), int(desired.y)],
                    "strict": bool(found.strict),
                    "source": "ring_search",
                },
            )

        ok = await self.builder.try_build("rax", U.BARRACKS, desired, cooldown=18)
        self._log(
            "building",
            {
                "event": "build_result",
                "name": "rax",
                "unit": str(U.BARRACKS),
                "desired": [int(desired.x), int(desired.y)],
                "ok": bool(ok),
            },
        )
        if ok:
            self.state.build.rax_started = True

    # =============================================================================
    # MACRO: REFINERY (geyser-based)
    # =============================================================================
    def _iter_geyser_candidates(self):
        out = []
        for tid in (U.VESPENEGEYSER, U.PROTOSSVESPENEGEYSER, U.SHAKURASVESPENEGEYSER):
            try:
                us = self.api.units(tid)
                if us:
                    out.extend(list(us))
            except Exception:
                pass
        if out:
            return out

        vg = getattr(self.bot, "vespene_geyser", None)
        if vg is not None:
            return vg
        vgs = getattr(self.bot, "vespene_geysers", None)
        if vgs is not None:
            return vgs
        gi = getattr(self.bot, "game_info", None)
        neutrals = getattr(gi, "map_neutral_units", None) if gi is not None else None
        if neutrals is not None:
            return neutrals
        nu = getattr(self.bot, "neutral_units", None)
        if nu is not None:
            return nu

        au = getattr(self.bot, "all_units", None)
        return au if au is not None else []

    def _is_geyser_unit(self, u) -> bool:
        tid = getattr(u, "type_id", None)
        if tid in (U.VESPENEGEYSER, U.PROTOSSVESPENEGEYSER, U.SHAKURASVESPENEGEYSER):
            return True
        nm = str(getattr(u, "name", "")).lower()
        return ("vespenegeyser" in nm) or ("shakurasvespenegeyser" in nm) or ("protossvespenegeyser" in nm)

    def _pos(self, u):
        p = getattr(u, "position", None)
        if p is not None:
            return p
        x = getattr(u, "x", None)
        y = getattr(u, "y", None)
        if x is not None and y is not None:
            return Point2((float(x), float(y)))
        return None

    async def _macro_refinery(self, cc) -> None:
        if not self._need_refinery():
            return

        self._emit_intent(
            "intent_ref",
            {
                "event": "intent",
                "what": "build",
                "unit": str(U.REFINERY),
                "reason": "after_rax",
            },
            every_n_it=15,
        )

        candidates = []
        for u in self._iter_geyser_candidates():
            if not self._is_geyser_unit(u):
                continue
            p = self._pos(u)
            if p is None:
                continue
            d = p.distance_to(cc.position)
            if d <= 12:
                candidates.append((d, u))

        if not candidates:
            self._emit_intent(
                "ref_no_candidates",
                {
                    "event": "ref_no_candidates",
                    "note": "missing neutrals/vespene list",
                    "cc": [int(cc.position.x), int(cc.position.y)],
                },
                every_n_it=30,
            )
            return

        candidates.sort(key=lambda t: t[0])

        ref_structs = self.api.units(U.REFINERY)
        workers = getattr(self.bot, "workers", None)
        if workers is None or not self.api.exists(workers):
            return

        for dist, geyser in candidates:
            gp = self._pos(geyser)
            if gp is None:
                continue

            if self.api.exists(self.api.closer_than(ref_structs, 1.0, gp)):
                continue

            if not self.econ.can_afford_reserved(U.REFINERY):
                return

            worker_pool = workers.gathering if hasattr(workers, "gathering") else workers
            worker = self.api.closest_to(worker_pool if self.api.exists(worker_pool) else workers, gp)
            if worker is None:
                return

            self._log(
                "building",
                {
                    "event": "build_attempt",
                    "name": "refinery",
                    "unit": str(U.REFINERY),
                    "geyser_dist": float(dist),
                    "pos": [int(gp.x), int(gp.y)],
                },
            )

            try:
                await self.bot.do(worker.build(U.REFINERY, geyser))
            except Exception as e:
                self._log(
                    "building",
                    {
                        "event": "build_attempt_fallback",
                        "name": "refinery",
                        "unit": str(U.REFINERY),
                        "pos": [int(gp.x), int(gp.y)],
                        "exc": str(e),
                    },
                )
                await self.bot.do(worker.build(U.REFINERY, gp))

            self.state.build.ref_started = True
            self._log(
                "building",
                {
                    "event": "build_result",
                    "name": "refinery",
                    "unit": str(U.REFINERY),
                    "pos": [int(gp.x), int(gp.y)],
                    "ok": True,
                },
            )
            return

    # =============================================================================
    # MACRO: FACTORY / STARPORT
    # =============================================================================
    async def _macro_factory(self, cc) -> None:
        if not self._need_factory():
            return

        desired = snap(cc.position.towards(self.bot.game_info.map_center, 12))
        self._emit_intent(
            "intent_factory",
            {
                "event": "intent",
                "what": "build",
                "unit": str(U.FACTORY),
                "desired": [int(desired.x), int(desired.y)],
                "reason": "after_ref",
            },
            every_n_it=15,
        )

        ok = await self.builder.try_build("factory", U.FACTORY, desired, cooldown=24)
        self._log(
            "building",
            {
                "event": "build_result",
                "name": "factory",
                "unit": str(U.FACTORY),
                "desired": [int(desired.x), int(desired.y)],
                "ok": bool(ok),
            },
        )
        if ok:
            self.state.build.factory_started = True

    async def _macro_starport(self, cc) -> None:
        if not self._need_starport():
            return

        desired = snap(cc.position.towards(self.bot.game_info.map_center, 14))
        self._emit_intent(
            "intent_starport",
            {
                "event": "intent",
                "what": "build",
                "unit": str(U.STARPORT),
                "desired": [int(desired.x), int(desired.y)],
                "reason": "after_factory",
            },
            every_n_it=15,
        )

        ok = await self.builder.try_build("starport", U.STARPORT, desired, cooldown=24)
        self._log(
            "building",
            {
                "event": "build_result",
                "name": "starport",
                "unit": str(U.STARPORT),
                "desired": [int(desired.x), int(desired.y)],
                "ok": bool(ok),
            },
        )
        if ok:
            self.state.build.starport_started = True

    # =============================================================================
    # PRODUÇÃO: MARINES / MEDIVAC
    # =============================================================================
    async def _produce_marines(self) -> None:
        if not self.state.build.rax_started:
            return

        rax = self.api.ready(U.BARRACKS)
        if not self.api.exists(rax):
            return

        if self.api.amount(self.api.units(U.MARINE)) >= self.marines_for_drop:
            return

        for b in self.api.idle(rax):
            if self.econ.can_afford_reserved(U.MARINE) and int(getattr(self.bot, "supply_left", 0) or 0) > 0:
                self._log("action", {"event": "do", "what": "train", "unit": "MARINE"})
                await self.bot.do(b.train(U.MARINE))

    async def _produce_medivac(self) -> None:
        if not self.state.build.starport_started:
            return

        sp = self.api.ready(U.STARPORT)
        if not self.api.exists(sp):
            return

        if self.api.amount(self.api.units(U.MEDIVAC)) >= 1:
            return

        for s in self.api.idle(sp):
            if self.econ.can_afford_reserved(U.MEDIVAC) and int(getattr(self.bot, "supply_left", 0) or 0) > 0:
                self._log("action", {"event": "do", "what": "train", "unit": "MEDIVAC"})
                await self.bot.do(s.train(U.MEDIVAC))

    # =============================================================================
    # STEP
    # =============================================================================
    async def step(self):
        self.econ.budget.reset()

        cc = self._main_cc()
        if cc is None:
            return

        snap0 = self.api.snapshot()
        if snap0.it % 10 == 0:
            self._log(
                "state",
                {
                    "event": "state",
                    "t": snap0.t,
                    "it": snap0.it,
                    "m": snap0.m,
                    "g": snap0.g,
                    "supply_used": snap0.supply_used,
                    "supply_cap": snap0.supply_cap,
                    "supply_left": snap0.supply_left,
                    "flags": {
                        "depot_started": bool(self.state.build.depot_started),
                        "rax_started": bool(self.state.build.rax_started),
                        "ref_started": bool(self.state.build.ref_started),
                        "factory_started": bool(self.state.build.factory_started),
                        "starport_started": bool(self.state.build.starport_started),
                    },
                },
            )

        await self.api.distribute_workers()

        self._reserve_critical()

        await self._macro_depot(cc)
        await self._macro_rax(cc)
        await self._macro_refinery(cc)
        await self._macro_factory(cc)
        await self._macro_starport(cc)

        await self._produce_marines()
        await self._produce_medivac()
        await self._macro_workers(cc)

        await self.drop.step()
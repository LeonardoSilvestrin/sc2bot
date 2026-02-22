from __future__ import annotations

from typing import Any, Dict, List, Optional

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from .api import BotAPI
from .utils import snap


class PlanExecutor:
    """Simple executor for strategy build/production plans.

    Supports conditions: have_gte, have_lte, minerals_gte, gas_gte,
    supply_left_gte, supply_left_lte.

    Supports actions: build (unit type string), train (unit type string).
    Build actions reuse Orchestrator.Builder.try_build for placement.
    """

    def __init__(self, orchestrator):
        self.orch = orchestrator
        self.bot = orchestrator.bot
        self.api = orchestrator.api
        self.builder = orchestrator.builder
        self.econ = orchestrator.econ
        self.place = orchestrator.place
        self.state = orchestrator.state
        # completed indices for one-shot steps
        self._completed_build: set[int] = set()
        self._completed_prod: set[int] = set()

    def _unit_from_name(self, name: str):
        if not name:
            return None
        n = name.strip().upper()
        return getattr(U, n, None)

    def _have_count(self, unit_name: str) -> int:
        ut = self._unit_from_name(unit_name)
        if ut is None:
            return 0
        existing = self.api.amount(self.api.units(ut))
        pending = self.api.already_pending(ut)
        return existing + pending

    def _check_when(self, when: Dict[str, Any]) -> bool:
        # empty when -> true
        if not when:
            return True
        # minerals/gas
        if "minerals_gte" in when:
            if int(getattr(self.bot, "minerals", 0) or 0) < int(when["minerals_gte"]):
                return False
        if "gas_gte" in when:
            if int(getattr(self.bot, "vespene", 0) or 0) < int(when["gas_gte"]):
                return False
        # supply
        if "supply_left_gte" in when:
            if int(getattr(self.bot, "supply_left", 0) or 0) < int(when["supply_left_gte"]):
                return False
        if "supply_left_lte" in when:
            if int(getattr(self.bot, "supply_left", 0) or 0) > int(when["supply_left_lte"]):
                return False
        # have_gte/have_lte maps
        if "have_gte" in when:
            for k, v in when["have_gte"].items():
                if self._have_count(k) < int(v):
                    return False
        if "have_lte" in when:
            for k, v in when["have_lte"].items():
                if self._have_count(k) > int(v):
                    return False
        return True

    async def _do_build(self, do: Dict[str, Any]) -> bool:
        name = do.get("build")
        if not name:
            return False
        ut = self._unit_from_name(name)
        if ut is None:
            return False
        # pick CC
        cc = self.orch._main_cc()
        if cc is None:
            return False
        # simple desired positioning similar to macros
        if ut == U.SUPPLYDEPOT:
            desired = snap(cc.position.towards(self.bot.game_info.map_center, 6))
        elif ut == U.BARRACKS:
            towards = snap(cc.position.towards(self.bot.game_info.map_center, 10))
            desired = towards
        elif ut == U.REFINERY:
            # find refinery spot near CC using orchestrator helper
            desired = self.place.find_refinery_spot(cc.position)
            if desired is None:
                return False
        elif ut == U.FACTORY:
            desired = snap(cc.position.towards(self.bot.game_info.map_center, 12))
        elif ut == U.STARPORT:
            desired = snap(cc.position.towards(self.bot.game_info.map_center, 14))
        else:
            desired = snap(cc.position.towards(self.bot.game_info.map_center, 10))

        # call builder
        ok = await self.builder.try_build(name.lower(), ut, desired)
        return bool(ok)

    async def _do_train(self, do: Dict[str, Any]) -> bool:
        name = do.get("train")
        if not name:
            return False
        ut = self._unit_from_name(name)
        if ut is None:
            return False
        # MARINE
        if ut == U.MARINE:
            rax = self.api.ready(U.BARRACKS)
            if not self.api.exists(rax):
                return False
            trained = False
            for b in self.api.idle(rax):
                if self.econ.can_afford_reserved(U.MARINE) and int(getattr(self.bot, "supply_left", 0) or 0) > 0:
                    try:
                        await self.bot.do(b.train(U.MARINE))
                        trained = True
                    except Exception:
                        pass
            return trained
        if ut == U.MEDIVAC:
            sp = self.api.ready(U.STARPORT)
            if not self.api.exists(sp):
                return False
            trained = False
            for s in self.api.idle(sp):
                if self.econ.can_afford_reserved(U.MEDIVAC) and int(getattr(self.bot, "supply_left", 0) or 0) > 0:
                    try:
                        await self.bot.do(s.train(U.MEDIVAC))
                        trained = True
                    except Exception:
                        pass
            return trained
        return False

    async def _do_addon(self, do: Dict[str, Any]) -> bool:
        addon = do.get("addon") or {}
        parent_name = addon.get("to")
        addon_type = (addon.get("type") or "").strip().upper()
        if not parent_name or not addon_type:
            return False
        parent_ut = self._unit_from_name(parent_name)
        if parent_ut is None:
            return False

        # guess addon unit name (e.g., BARRACKS + TECHLAB -> BARRACKSTECHLAB)
        cand_name = f"{parent_name.strip().upper()}{addon_type}"
        addon_ut = getattr(U, cand_name, None)
        if addon_ut is None:
            return False

        # find a ready parent without a nearby addon
        parents = self.api.ready(parent_ut)
        if not self.api.exists(parents):
            return False

        for p in parents:
            # skip if an addon of this type already exists very near
            if self.api.exists(self.api.closer_than(self.api.units(addon_ut), 1.5, p.position)):
                continue
            try:
                await self.bot.do(p.build(addon_ut))
                return True
            except Exception:
                try:
                    # fallback: try parent.build with no await
                    await self.bot.do(p.build(addon_ut))
                    return True
                except Exception:
                    continue
        return False

    async def step(self) -> None:
        strat = getattr(self.orch, "strat", None)
        if strat is None:
            return
        # build plan
        build_plan = getattr(strat, "build_plan", None) or []
        for i, step in enumerate(build_plan):
            if i in self._completed_build:
                continue
            when = step.get("when", {}) or {}
            do = step.get("do", {}) or {}
            if not self._check_when(when):
                continue
            # dispatch action: build or addon
            if "build" in do:
                ok = await self._do_build(do)
            elif "addon" in do:
                ok = await self._do_addon(do)
            else:
                ok = False
            # if executed, and step has once (default True), mark completed
            once = step.get("once", True)
            if ok and once:
                self._completed_build.add(i)

        # production plan
        prod_plan = getattr(strat, "production_plan", None) or []
        for i, step in enumerate(prod_plan):
            if i in self._completed_prod:
                continue
            when = step.get("when", {}) or {}
            do = step.get("do", {}) or {}
            if not self._check_when(when):
                continue
            ok = False
            if "train" in do:
                ok = await self._do_train(do)
            elif "addon" in do:
                ok = await self._do_addon(do)
            if ok and step.get("once", False):
                self._completed_prod.add(i)
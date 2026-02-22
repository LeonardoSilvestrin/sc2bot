# bot/engine/builder.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional
import inspect

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.ability_id import AbilityId as A
from sc2.ids.upgrade_id import UpgradeId as Up


@dataclass
class LastAction:
    ok: bool
    kind: str
    unit: str
    reason: str
    details: Any | None = None


class Builder:
    def __init__(self, bot, economy, placement, state, logger=None):
        self.bot = bot
        self.economy = economy
        self.placement = placement
        self.state = state
        self.log = logger
        self.last: LastAction | None = None

    # ----------------------------
    # robust unit access
    # ----------------------------
    def _iter_owned(self) -> Iterable[Any]:
        st = getattr(self.bot, "state", None)
        if st is not None and hasattr(st, "units"):
            return st.units
        if hasattr(self.bot, "all_units"):
            return self.bot.all_units
        return self.bot.units

    def _iter_all_units(self) -> Iterable[Any]:
        st = getattr(self.bot, "state", None)
        if st is not None and hasattr(st, "units"):
            return st.units
        if hasattr(self.bot, "all_units"):
            return self.bot.all_units
        return self.bot.units

    def _owned_of_type(self, unit_type: U) -> list[Any]:
        out = []
        for u in self._iter_owned():
            is_mine = getattr(u, "is_mine", None)
            if is_mine is not None and not is_mine:
                continue
            if getattr(u, "type_id", None) == unit_type:
                out.append(u)
        return out

    # ----------------------------
    # geyser access (neutral units)
    # ----------------------------
    def _iter_geyser_candidates(self) -> list[Any]:
        bot = self.bot
        st = getattr(bot, "state", None)

        if st is not None and hasattr(st, "vespene_geyser"):
            try:
                gs = list(st.vespene_geyser)
                if gs:
                    return gs
            except Exception:
                pass

        if hasattr(bot, "vespene_geyser"):
            try:
                gs = list(bot.vespene_geyser)
                if gs:
                    return gs
            except Exception:
                pass

        if st is not None and hasattr(st, "neutral_units"):
            try:
                gs = [u for u in st.neutral_units if getattr(u, "type_id", None) == U.VESPENEGEYSER]
                if gs:
                    return gs
            except Exception:
                pass

        return [u for u in self._iter_all_units() if getattr(u, "type_id", None) == U.VESPENEGEYSER]

    # ----------------------------
    # counts
    # ----------------------------
    def have(self, unit_type: U) -> int:
        return len(self._owned_of_type(unit_type))

    def ready(self, unit_type: U) -> int:
        units = self._owned_of_type(unit_type)
        return sum(1 for u in units if getattr(u, "is_ready", False))

    def pending(self, unit_type: U) -> int:
        return int(self.bot.already_pending(unit_type))

    def total(self, unit_type: U) -> int:
        return self.have(unit_type) + self.pending(unit_type)

    # ----------------------------
    # low-level do() compatible
    # ----------------------------
    async def _do(self, cmd) -> bool:
        fn = getattr(self.bot, "do", None)
        if fn is None:
            return False

        res = fn(cmd)
        if inspect.isawaitable(res):
            await res
            return True

        if isinstance(res, bool):
            return res
        return True

    # ----------------------------
    # upgrades (robust)
    # ----------------------------
    def has_upgrade(self, up: Up) -> bool:
        st = getattr(self.bot, "state", None)
        ups = getattr(st, "upgrades", None)
        if ups is None:
            return False
        try:
            # python-sc2 geralmente usa set[UpgradeId]
            return up in ups
        except Exception:
            # forks podem usar ints
            try:
                return int(up.value) in set(int(x) for x in ups)
            except Exception:
                return False

    def pending_upgrade(self, up: Up) -> int:
        fn = getattr(self.bot, "already_pending_upgrade", None)
        if fn is None:
            return 0
        try:
            return int(fn(up))
        except Exception:
            try:
                return int(fn(int(up.value)))
            except Exception:
                return 0

    # ----------------------------
    # actions
    # ----------------------------
    async def try_build(self, unit_type: U, *, near=None) -> bool:
        bot = self.bot

        if not bot.can_afford(unit_type):
            self._fail("build", unit_type, "cant_afford", {"minerals": int(bot.minerals), "gas": int(bot.vespene)})
            return False

        if bot.workers.amount == 0:
            self._fail("build", unit_type, "no_workers", None)
            return False

        if unit_type == U.REFINERY:
            ths = getattr(bot, "townhalls", None)
            th = ths.ready.first if ths and ths.ready else None
            if th is None:
                self._fail("build", unit_type, "no_townhall", None)
                return False

            geysers = sorted(self._iter_geyser_candidates(), key=lambda g: g.distance_to(th))
            if not geysers:
                self._fail("build", unit_type, "no_geyser_candidates", None)
                return False

            existing_refineries = self._owned_of_type(U.REFINERY)
            for g in geysers:
                occupied = any(r.distance_to(g) < 1.0 for r in existing_refineries)
                if occupied:
                    continue

                await bot.build(U.REFINERY, near=g)
                self._ok("build", unit_type, {"geyser_pos": [float(g.position.x), float(g.position.y)]})
                return True

            self._fail("build", unit_type, "all_geysers_occupied", None)
            return False

        pos = await self.placement.find_placement(unit_type, near=near)
        if pos is None:
            self._fail("build", unit_type, "no_placement", None)
            return False

        await bot.build(unit_type, near=pos)
        self._ok("build", unit_type, {"pos": [float(pos.x), float(pos.y)]})
        return True

    async def try_train(self, unit_type: U, *, from_type: U) -> bool:
        bot = self.bot

        producers = [u for u in self._owned_of_type(from_type) if getattr(u, "is_ready", False)]
        if not producers:
            self._fail("train", unit_type, "no_producer", {"from": str(from_type)})
            return False

        if not bot.can_afford(unit_type):
            self._fail("train", unit_type, "cant_afford", {"minerals": int(bot.minerals), "gas": int(bot.vespene)})
            return False

        if bot.supply_left <= 0:
            self._fail("train", unit_type, "no_supply", {"supply_left": int(bot.supply_left)})
            return False

        for b in producers:
            if not getattr(b, "is_idle", False):
                continue
            b.train(unit_type)
            self._ok("train", unit_type, {"from": str(from_type)})
            return True

        self._fail("train", unit_type, "all_busy", {"from": str(from_type)})
        return False

    # ----------------------------
    # addons
    # ----------------------------
    async def try_addon(self, *, on: U, addon: str) -> bool:
        """
        addon: "TECHLAB" | "REACTOR"
        """
        bot = self.bot
        addon = addon.strip().upper()

        parents = [b for b in self._owned_of_type(on) if getattr(b, "is_ready", False)]
        if not parents:
            self._fail("addon", on, "no_parent", {"on": str(on)})
            return False

        # precisa estar idle pra construir addon
        parent = None
        for b in parents:
            if getattr(b, "is_idle", False):
                parent = b
                break
        if parent is None:
            self._fail("addon", on, "no_idle_parent", {"on": str(on)})
            return False

        # mapeia ability + custo via can_afford(ability)
        if on == U.BARRACKS and addon == "TECHLAB":
            ability = A.BUILD_TECHLAB_BARRACKS
            unit_name = "BARRACKSTECHLAB"
        elif on == U.BARRACKS and addon == "REACTOR":
            ability = A.BUILD_REACTOR_BARRACKS
            unit_name = "BARRACKSREACTOR"
        elif on == U.FACTORY and addon == "TECHLAB":
            ability = A.BUILD_TECHLAB_FACTORY
            unit_name = "FACTORYTECHLAB"
        elif on == U.FACTORY and addon == "REACTOR":
            ability = A.BUILD_REACTOR_FACTORY
            unit_name = "FACTORYREACTOR"
        elif on == U.STARPORT and addon == "TECHLAB":
            ability = A.BUILD_TECHLAB_STARPORT
            unit_name = "STARPORTTECHLAB"
        elif on == U.STARPORT and addon == "REACTOR":
            ability = A.BUILD_REACTOR_STARPORT
            unit_name = "STARPORTREACTOR"
        else:
            self._fail("addon", on, "unsupported_addon", {"on": str(on), "addon": addon})
            return False

        # custo
        can_afford_ability = getattr(bot, "can_afford", None)
        if callable(can_afford_ability):
            try:
                if not bot.can_afford(ability):
                    self._fail("addon", on, "cant_afford", {"ability": str(ability)})
                    return False
            except Exception:
                # alguns forks não suportam can_afford(AbilityId); deixa passar e falha no action result se houver
                pass

        ok = await self._do(parent(ability))
        if ok:
            self._ok("addon", on, {"on": on.name, "addon": addon, "unit": unit_name, "parent_tag": int(parent.tag)})
            return True

        self._fail("addon", on, "do_failed", {"on": on.name, "addon": addon})
        return False

    # ----------------------------
    # research
    # ----------------------------
    async def try_research(self, upgrade: Up) -> bool:
        bot = self.bot

        if self.has_upgrade(upgrade):
            self._fail("research", U.BARRACKS, "already_done", {"upgrade": str(upgrade)})
            return False

        if self.pending_upgrade(upgrade) > 0:
            self._fail("research", U.BARRACKS, "already_pending", {"upgrade": str(upgrade)})
            return False

        # STIMPACK precisa de Barracks Tech Lab
        if upgrade == Up.STIMPACK:
            labs = [x for x in self._owned_of_type(U.BARRACKSTECHLAB) if getattr(x, "is_ready", False)]
            if not labs:
                self._fail("research", U.BARRACKSTECHLAB, "no_techlab", {"upgrade": "STIMPACK"})
                return False

            lab = None
            for x in labs:
                if getattr(x, "is_idle", False):
                    lab = x
                    break
            if lab is None:
                self._fail("research", U.BARRACKSTECHLAB, "all_busy", {"upgrade": "STIMPACK"})
                return False

            # custo (python-sc2 geralmente aceita can_afford(AbilityId.RESEARCH_STIMPACK))
            try:
                if not bot.can_afford(A.RESEARCH_STIMPACK):
                    self._fail("research", U.BARRACKSTECHLAB, "cant_afford", {"upgrade": "STIMPACK"})
                    return False
            except Exception:
                pass

            ok = await self._do(lab(A.RESEARCH_STIMPACK))
            if ok:
                self._ok("research", U.BARRACKSTECHLAB, {"upgrade": "STIMPACK", "lab_tag": int(lab.tag)})
                return True

            self._fail("research", U.BARRACKSTECHLAB, "do_failed", {"upgrade": "STIMPACK"})
            return False

        self._fail("research", U.BARRACKS, "unsupported_upgrade", {"upgrade": str(upgrade)})
        return False

    # ----------------------------
    # logging helpers
    # ----------------------------
    def _ok(self, kind: str, unit_type: U, details: dict | None):
        self.last = LastAction(ok=True, kind=kind, unit=str(unit_type.name), reason="ok", details=details)
        if self.log:
            self.log.emit(
                "action_ok",
                {"kind": kind, "unit": unit_type.name, **(details or {})},
                meta={"iter": int(self.state.iteration)},
            )

    def _fail(self, kind: str, unit_type: U, reason: str, details: dict | None):
        self.last = LastAction(ok=False, kind=kind, unit=str(unit_type.name), reason=reason, details=details)
        if self.log:
            payload = {"kind": kind, "unit": unit_type.name, "reason": reason}
            if details:
                payload.update(details)
            self.log.emit("action_fail", payload, meta={"iter": int(self.state.iteration)})
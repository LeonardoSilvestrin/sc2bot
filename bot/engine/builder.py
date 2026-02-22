from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from sc2.ids.unit_typeid import UnitTypeId as U


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
        """
        Retorna TODAS as unidades do player (inclui buildings), independente do fork.
        Ordem de preferência:
          1) bot.state.units (geralmente inclui tudo)
          2) bot.all_units
          3) bot.units (pior caso)
        """
        st = getattr(self.bot, "state", None)
        if st is not None and hasattr(st, "units"):
            return st.units
        if hasattr(self.bot, "all_units"):
            return self.bot.all_units
        return self.bot.units
    def _iter_all_units(self) -> Iterable[Any]:
        """
        Retorna todas as unidades conhecidas pelo bot (inclui neutras).
        Preferência:
        1) bot.state.units
        2) bot.all_units
        3) bot.units (fallback)
        """
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
        """
        Retorna geysers (Units neutros) de forma robusta.
        Não assume que 'neutral_units' exista, nem que 'vespene_geyser' esteja populado.
        """
        bot = self.bot
        st = getattr(bot, "state", None)

        # 1) Algumas versões expõem isso no state
        if st is not None and hasattr(st, "vespene_geyser"):
            try:
                gs = list(st.vespene_geyser)
                if gs:
                    return gs
            except Exception:
                pass

        # 2) Outras expõem no próprio bot (property)
        if hasattr(bot, "vespene_geyser"):
            try:
                gs = list(bot.vespene_geyser)
                if gs:
                    return gs
            except Exception:
                pass

        # 3) neutral_units (quando existe)
        if st is not None and hasattr(st, "neutral_units"):
            try:
                gs = [u for u in st.neutral_units if getattr(u, "type_id", None) == U.VESPENEGEYSER]
                if gs:
                    return gs
            except Exception:
                pass

        # 4) fallback mais confiável: varrer TODAS as units conhecidas
        gs = [u for u in self._iter_all_units() if getattr(u, "type_id", None) == U.VESPENEGEYSER]
        return gs
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

        # ----------------------------
        # SPECIAL CASE: REFINERY
        # - no teu fork, bot.build(REFINERY, near=...) exige Unit (geyser), não Point2
        # ----------------------------
        if unit_type == U.REFINERY:
            ths = getattr(bot, "townhalls", None)
            th = ths.ready.first if ths and ths.ready else None
            if th is None:
                self._fail("build", unit_type, "no_townhall", None)
                return False

            geysers = self._iter_geyser_candidates()
            # pegue geysers perto do CC (distância típica do main)
            geysers = sorted(geysers, key=lambda g: g.distance_to(th))

            if not geysers:
                self._fail("build", unit_type, "no_geyser_candidates", None)
                return False

            existing_refineries = self._owned_of_type(U.REFINERY)

            for g in geysers:
                # considera ocupado se já existe refinery em cima
                occupied = any(r.distance_to(g) < 1.0 for r in existing_refineries)
                if occupied:
                    continue

                # AQUI é o ponto: passar o geyser Unit
                await bot.build(U.REFINERY, near=g)

                self._ok(
                    "build",
                    unit_type,
                    {"geyser_pos": [float(g.position.x), float(g.position.y)]},
                )
                return True

            self._fail("build", unit_type, "all_geysers_occupied", None)
            return False

        # ----------------------------
        # NORMAL BUILDINGS (Point2 placement)
        # ----------------------------
        pos = await self.placement.find_placement(unit_type, near=near)
        if pos is None:
            self._fail("build", unit_type, "no_placement", None)
            return False

        await bot.build(unit_type, near=pos)
        self._ok("build", unit_type, {"pos": [float(pos.x), float(pos.y)]})
        return True

    async def try_train(self, unit_type: U, *, from_type: U) -> bool:
        bot = self.bot

        # NÃO confie em bot.units(from_type) no seu fork.
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
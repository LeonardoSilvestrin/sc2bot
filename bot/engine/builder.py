# builder.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sc2.ids.unit_typeid import UnitTypeId as U


@dataclass
class ActionResult:
    ok: bool
    reason: str = ""
    details: dict | None = None


class Builder:
    """
    Camada de emissão de ações (idempotent-ish).
    - NÃO decide estratégia
    - Só tenta construir/treinar e retorna motivo em caso de falha
    - Não usa .structures() (compatível com fork units-only)
    """

    def __init__(self, bot: Any, economy: Any, placement: Any, ctx: Any, logger: Any | None = None):
        self.bot = bot
        self.economy = economy
        self.placement = placement
        self.ctx = ctx
        self.log = logger

        # útil para o executor logar "blocked" com contexto
        self.last: ActionResult = ActionResult(ok=False, reason="init")

    # ----------------------------
    # counts (engine helpers)
    # ----------------------------
    def have(self, unit_type: U) -> int:
        return self.bot.units(unit_type).amount

    def ready(self, unit_type: U) -> int:
        return self.bot.units(unit_type).ready.amount

    def pending(self, unit_type: U) -> int:
        return int(self.bot.already_pending(unit_type))

    def total(self, unit_type: U) -> int:
        return self.have(unit_type) + self.pending(unit_type)

    # ----------------------------
    # actions (idempotent-ish)
    # ----------------------------
    async def try_build(self, unit_type: U, *, near=None) -> bool:
        bot = self.bot

        if bot.workers.amount == 0:
            return self._fail("build", unit_type, "no_workers")

        if not bot.can_afford(unit_type):
            return self._fail("build", unit_type, "cant_afford", minerals=int(bot.minerals), gas=int(bot.vespene))

        pos = await self.placement.find_placement(unit_type, near=near)
        if pos is None:
            return self._fail("build", unit_type, "no_placement")

        await bot.build(unit_type, near=pos)

        return self._ok("build", unit_type, pos=(float(pos.x), float(pos.y)))

    async def try_train(self, unit_type: U, *, from_type: U) -> bool:
        bot = self.bot
        buildings = bot.units(from_type).ready

        if not buildings:
            return self._fail("train", unit_type, "no_producer", from_type=from_type.name)

        if not bot.can_afford(unit_type):
            return self._fail("train", unit_type, "cant_afford", minerals=int(bot.minerals), gas=int(bot.vespene))

        if bot.supply_left <= 0:
            return self._fail("train", unit_type, "supply_blocked", supply_left=int(bot.supply_left))

        for b in buildings:
            if not b.is_idle:
                continue

            b.train(unit_type)
            return self._ok("train", unit_type, from_type=from_type.name, producer_tag=int(b.tag))

        return self._fail("train", unit_type, "no_idle_producer", from_type=from_type.name)

    # ----------------------------
    # internal logging helpers
    # ----------------------------
    def _ok(self, kind: str, unit_type: U, **details) -> bool:
        self.last = ActionResult(ok=True, reason="ok", details={"kind": kind, "unit": unit_type.name, **details})
        if self.log:
            self.log.emit(
                "action_ok",
                {"kind": kind, "unit": unit_type.name, **details},
                meta={"iter": int(self.ctx.iteration)},
            )
        return True

    def _fail(self, kind: str, unit_type: U, reason: str, **details) -> bool:
        self.last = ActionResult(ok=False, reason=reason, details={"kind": kind, "unit": unit_type.name, **details})
        if self.log:
            self.log.emit(
                "action_fail",
                {"kind": kind, "unit": unit_type.name, "reason": reason, **details},
                meta={"iter": int(self.ctx.iteration)},
            )
        return False
#bot/behaviors/main_wall.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId as U

from .base import TickBudget


@dataclass
class MainWallRuntime:
    complete: bool = False
    next_loop: int = 0


class MainWallOpenerBehavior:
    """
    Só serve quando você quer OVERRIDE (rush/force):
      - force 2 depots + 1 barracks ASAP, nos spots da MAIN wall.
    Se force=False, esse Behavior nem deve rodar (ver TerranBot._active_pairs).
    """

    name = "main_wall"

    def __init__(
        self,
        bot: Any,
        ctx: Any,
        builder: Any,
        placement: Any,
        *,
        logger: Any | None = None,
        debug: bool = True,
    ):
        self.bot = bot
        self.ctx = ctx
        self.builder = builder
        self.place = placement
        self.log = logger
        self.debug = debug
        self.rt = MainWallRuntime()

        # fase interna para não repetir build enquanto está pending/invisível
        self.ctx.owner_meta.setdefault("main_wall_force", {"phase": 0})

    def _iter(self) -> int:
        return int(getattr(self.ctx, "iteration", 0))

    def _loop(self) -> int:
        st = getattr(self.bot, "state", None)
        gl = getattr(st, "game_loop", None)
        if gl is not None:
            return int(gl)
        return self._iter()

    def _emit(self, event: str, payload: dict):
        if self.log:
            self.log.emit(event, payload, meta={"iter": self._iter()})

    def _phase(self) -> int:
        return int(self.ctx.owner_meta.get("main_wall_force", {}).get("phase", 0))

    def _set_phase(self, p: int) -> None:
        self.ctx.owner_meta.setdefault("main_wall_force", {})
        self.ctx.owner_meta["main_wall_force"]["phase"] = int(p)

    async def step(self, budget: TickBudget, cfg: dict) -> bool:
        loop = self._loop()
        if loop < int(self.rt.next_loop):
            return False
        if budget.remaining <= 0:
            self.rt.next_loop = loop + 8
            return False
        if self.rt.complete:
            return False

        phase = self._phase()

        # 0 -> build depot 1
        # 1 -> build depot 2
        # 2 -> build barracks 1
        # 3 -> done
        did = False
        if phase == 0:
            did = await self.builder.try_build(U.SUPPLYDEPOT, wall_pref="MAIN")
            self._emit("main_wall_force", {"phase": 0, "want": "DEPOT#1", "did": bool(did)})
            if did:
                self._set_phase(1)
        elif phase == 1:
            did = await self.builder.try_build(U.SUPPLYDEPOT, wall_pref="MAIN")
            self._emit("main_wall_force", {"phase": 1, "want": "DEPOT#2", "did": bool(did)})
            if did:
                self._set_phase(2)
        elif phase == 2:
            did = await self.builder.try_build(U.BARRACKS, wall_pref="MAIN")
            self._emit("main_wall_force", {"phase": 2, "want": "BARRACKS#1", "did": bool(did)})
            if did:
                self._set_phase(3)
        else:
            self.rt.complete = True
            self._emit("main_wall_force_complete", {"complete": True})
            return False

        if did:
            budget.spend(1)
            self.rt.next_loop = loop + 6
            return True

        self.rt.next_loop = loop + 10
        return False
#bot/behaviors/wall.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, List, Tuple

import inspect

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.ability_id import AbilityId as A
from sc2.position import Point2

from .base import TickBudget


@dataclass
class WallRuntime:
    complete: bool = False
    last_open: Optional[bool] = None
    next_loop: int = 0


class WallBehavior:
    """
    Controla o "portão" (SupplyDepots) da wall:
    - OPEN por padrão (SCV desce).
    - CLOSE se inimigo terrestre perto da rampa.
    - Marca wall como 'complete' quando as peças principais estiverem prontas.
    """

    name = "wall"

    def __init__(self, bot: Any, ctx: Any, placement: Any, *, logger: Any | None = None, debug: bool = True):
        self.bot = bot
        self.ctx = ctx
        self.place = placement
        self.log = logger
        self.debug = debug
        self.rt = WallRuntime()

        # chave de meta
        self.meta_key = "wall:natural"

    def _loop(self) -> int:
        st = getattr(self.bot, "state", None)
        gl = getattr(st, "game_loop", None)
        if gl is not None:
            return int(gl)
        it = getattr(self.ctx, "iteration", None)
        return int(it) if it is not None else 0

    def _iter(self) -> int:
        return int(getattr(self.ctx, "iteration", 0))

    def _emit(self, event: str, payload: dict):
        if self.log:
            self.log.emit(event, payload, meta={"iter": self._iter()})

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

    # -------------------
    # helpers de matching
    # -------------------
    def _wall_planner(self):
        # Placement.wall = WallPlanner(...)
        return getattr(self.place, "wall", None)

    def _get_wall_spots(self) -> tuple[Optional[Point2], List[Point2]]:
        wp = self._wall_planner()
        if wp is None:
            return None, []

        anchor = wp.wall_anchor()
        depots = wp.wall_spots_for(U.SUPPLYDEPOT)
        depots = [p for p in depots if p is not None]
        return anchor, depots[:2]

    def _find_my_depot_near(self, pos: Point2, *, max_d: float = 1.0):
        if not hasattr(self.bot, "units"):
            return None
        depots = self.bot.units(U.SUPPLYDEPOT)
        if not depots:
            return None
        best = None
        best_d = 1e18
        for d in depots.ready:
            dist = float(d.distance_to(pos))
            if dist < best_d:
                best = d
                best_d = dist
        if best is not None and best_d <= float(max_d):
            return best
        return None

    def _depot_is_lowered(self, depot: Any) -> bool:
        # python-sc2 costuma expor is_lowered; se não tiver, assume False (conservador)
        v = getattr(depot, "is_lowered", None)
        if v is None:
            return False
        try:
            return bool(v)
        except Exception:
            return False

    def _friendly_blocking_door(self, depot_positions: List[Point2], *, radius: float = 2.25) -> bool:
        # se tiver unidade amiga (terra) muito em cima do choke, não levanta
        if not hasattr(self.bot, "units"):
            return False
        all_my = getattr(self.bot, "units", None)
        if all_my is None:
            return False

        # pega tudo que é meu e terrestre (inclui worker/marine etc.)
        # (sem estruturas)
        try:
            mine = [u for u in self.bot.units if getattr(u, "is_mine", True)]
        except Exception:
            mine = []

        if not mine:
            # fallback: tenta bot.units.filter?
            mine = []

        r = float(radius)
        for p in depot_positions:
            for u in mine:
                if getattr(u, "is_structure", False):
                    continue
                if getattr(u, "is_flying", False):
                    continue
                try:
                    if float(u.distance_to(p)) <= r:
                        return True
                except Exception:
                    continue
        return False

    def _enemy_ground_threat_near(self, anchor: Point2, *, radius: float = 18.0) -> bool:
        enemies = getattr(self.bot, "enemy_units", None)
        if enemies is None:
            return False
        r = float(radius)

        # ameaça = unidades inimigas terrestres (structures não contam)
        try:
            for e in enemies:
                if getattr(e, "is_structure", False):
                    continue
                if getattr(e, "is_flying", False):
                    continue
                if float(e.distance_to(anchor)) <= r:
                    return True
        except Exception:
            return False
        return False

    def _set_wall_meta(self, *, complete: bool | None = None, open_now: bool | None = None) -> None:
        self.ctx.owner_meta.setdefault(self.meta_key, {})
        if complete is not None:
            self.ctx.owner_meta[self.meta_key]["complete"] = bool(complete)
        if open_now is not None:
            self.ctx.owner_meta[self.meta_key]["open"] = bool(open_now)

    # -------------------
    # main
    # -------------------
    async def step(self, budget: TickBudget, cfg: dict) -> bool:
        # throttling simples pra não gastar tick
        loop = self._loop()
        if loop < int(self.rt.next_loop):
            return False

        anchor, depot_spots = self._get_wall_spots()
        if anchor is None or len(depot_spots) < 2:
            self.rt.next_loop = loop + 22
            return False

        d1 = self._find_my_depot_near(depot_spots[0])
        d2 = self._find_my_depot_near(depot_spots[1])
        have_two = bool(d1 is not None and d2 is not None)

        # completa quando os 2 depots existem e estão prontos (barracks pode variar por mapa/fork)
        complete_now = have_two and getattr(d1, "is_ready", True) and getattr(d2, "is_ready", True)
        if complete_now and not self.rt.complete:
            self.rt.complete = True
            self._set_wall_meta(complete=True)
            self._emit(
                "wall_complete",
                {
                    "depots": [
                        int(getattr(d1, "tag", 0)),
                        int(getattr(d2, "tag", 0)),
                    ],
                    "spots": [
                        [float(depot_spots[0].x), float(depot_spots[0].y)],
                        [float(depot_spots[1].x), float(depot_spots[1].y)],
                    ],
                },
            )

        # Decide OPEN/CLOSE
        threat = self._enemy_ground_threat_near(anchor, radius=float(getattr(cfg, "threat_radius", 18.0)))
        want_open = not threat  # padrão: aberto
        want_close = not want_open

        # não fecha se tem aliado na porta
        if want_close and self._friendly_blocking_door(depot_spots, radius=float(getattr(cfg, "door_clear_radius", 2.25))):
            want_close = False
            want_open = True

        # Sem budget, sem ação
        if budget.remaining <= 0:
            self.rt.next_loop = loop + 8
            return False

        issued = False
        for dep in [d1, d2]:
            if dep is None:
                continue

            lowered = self._depot_is_lowered(dep)

            # se quer OPEN -> depot tem que estar lowered
            if want_open and not lowered:
                ok = await self._do(dep(A.MORPH_SUPPLYDEPOT_LOWER))
                if ok:
                    budget.spend(1)
                    issued = True

            # se quer CLOSE -> depot tem que estar raised (not lowered)
            if want_close and lowered:
                ok = await self._do(dep(A.MORPH_SUPPLYDEPOT_RAISE))
                if ok:
                    budget.spend(1)
                    issued = True

            if budget.remaining <= 0:
                break

        if issued:
            self.rt.last_open = bool(want_open)
            self._set_wall_meta(open_now=bool(want_open))
            self._emit(
                "wall_gate",
                {
                    "open": bool(want_open),
                    "threat": bool(threat),
                    "anchor": [float(anchor.x), float(anchor.y)],
                },
            )
            self.rt.next_loop = loop + 6
            return True

        self.rt.next_loop = loop + 12
        return False
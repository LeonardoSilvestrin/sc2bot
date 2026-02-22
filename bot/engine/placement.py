#bot/engine/placement.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Dict, List, Tuple

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.engine.wall import WallPlanner


def _snap_half(p: Point2) -> Point2:
    x = round(float(p.x) * 2.0) / 2.0
    y = round(float(p.y) * 2.0) / 2.0
    return Point2((x, y))


def _near_key(p: Point2 | None) -> str:
    """
    Cache key estável para 'near'. Não precisa ser perfeito; precisa ser consistente.
    """
    if p is None:
        return "NONE"
    p = _snap_half(p)
    return f"{float(p.x):.1f},{float(p.y):.1f}"


@dataclass
class _Reservation:
    unit_type: U
    pos: Point2
    expires_iter: int


class Placement:
    """
    Regra:
      - Se main_wall_enabled=True:
          * tenta colocar os 2 primeiros SUPPLYDEPOT e a 1a BARRACKS nos spots da MAIN wall,
            baseado em ocupação real (não em contador interno).
      - Se main_wall_enabled=False:
          * tudo usa placement normal.

    Patch importante:
      - Anchor default NÃO pode depender de townhalls.ready.first (ordem não é garantida).
      - Cache precisa respeitar o 'near', senão STARPORT pode “grudar” em base errada.
    """

    def __init__(
        self,
        bot: Any,
        *,
        ctx: Any | None = None,
        logger: Any | None = None,
        wall_main: bool = True,
        wall_natural: bool = False,
        main_wall_enabled: bool = True,
        reserve_ttl_iters: int = 80,
        debug: bool = True,
        # segurança: se cache estiver muito longe do near, ignora
        cache_max_dist: float = 18.0,
    ):
        self.bot = bot
        self.ctx = ctx
        self.log = logger
        self.debug = debug

        self.wall_main = bool(wall_main)
        self.wall_natural = bool(wall_natural)
        self.main_wall_enabled = bool(main_wall_enabled)
        self.reserve_ttl_iters = int(reserve_ttl_iters)
        self.cache_max_dist = float(cache_max_dist)

        self.wall = WallPlanner(bot, ctx=ctx, logger=logger, debug=debug) if ctx is not None else None

        # cache agora é por (unit_type + near_key)
        self._cache: Dict[str, Point2] = {}
        self._reservations: List[_Reservation] = []

        self._wall_slots: Dict[str, Dict[str, List[Point2]]] = {
            "MAIN": {"SUPPLYDEPOT": [], "BARRACKS": []},
            "NATURAL": {"SUPPLYDEPOT": [], "BARRACKS": []},
        }

    def _emit(self, event: str, payload: dict) -> None:
        if self.log:
            self.log.emit(event, payload, meta={"iter": int(getattr(self.ctx, "iteration", 0) if self.ctx else 0)})

    def _iter(self) -> int:
        return int(getattr(self.ctx, "iteration", 0) if self.ctx else 0)

    def _cleanup_reservations(self) -> None:
        it = self._iter()
        self._reservations = [r for r in self._reservations if int(r.expires_iter) > it]

    def _is_reserved(self, unit_type: U, pos: Point2) -> bool:
        for r in self._reservations:
            if r.unit_type == unit_type and float(r.pos.distance_to(pos)) < 0.25:
                return True
        return False

    def _reserve(self, unit_type: U, pos: Point2) -> None:
        it = self._iter()
        self._reservations.append(_Reservation(unit_type=unit_type, pos=pos, expires_iter=it + self.reserve_ttl_iters))

    async def _can_place(self, unit_type: U, pos: Point2) -> bool:
        bot = self.bot

        fn = getattr(bot, "can_place_single", None)
        if callable(fn):
            try:
                return bool(await fn(unit_type, pos))
            except Exception:
                pass

        fn = getattr(bot, "can_place", None)
        if callable(fn):
            try:
                res = fn(unit_type, [pos])
                if isinstance(res, list) and res:
                    return bool(res[0])
                return bool(res)
            except Exception:
                pass

        # fallback permissivo (mantém o teu comportamento), mas agora com logs melhores a montante
        return True

    def _pick_main_anchor(self) -> Point2:
        """
        Anchor default deve ser MAIN de forma estável.

        Heurística:
          1) Se ctx tiver my_main, usa.
          2) Senão, pega o townhall ready mais perto de start_location.
          3) Senão, start_location.
        """
        bot = self.bot

        # (1) ctx.my_main (quando existir)
        if self.ctx is not None:
            mm = getattr(self.ctx, "my_main", None)
            if isinstance(mm, Point2):
                self._emit("placement_anchor", {"kind": "ctx.my_main", "pos": [float(mm.x), float(mm.y)]})
                return mm

        # (2) townhall mais perto do start_location
        ths = getattr(bot, "townhalls", None)
        if ths is not None:
            try:
                ready = ths.ready
                if ready:
                    sl = bot.start_location
                    best = min(ready, key=lambda u: float(u.position.distance_to(sl)))
                    p = best.position
                    self._emit(
                        "placement_anchor",
                        {"kind": "townhall_closest_to_start", "pos": [float(p.x), float(p.y)]},
                    )
                    return p
            except Exception:
                pass

        # (3) start_location
        sl = bot.start_location
        self._emit("placement_anchor", {"kind": "start_location", "pos": [float(sl.x), float(sl.y)]})
        return sl

    async def _fallback_find(self, unit_type: U, *, near: Point2 | None) -> Point2 | None:
        bot = self.bot
        if near is None:
            near = self._pick_main_anchor()
        try:
            return await bot.find_placement(unit_type, near=near, placement_step=2)
        except Exception as e:
            self._emit(
                "placement_find_placement_exc",
                {"unit": unit_type.name, "near": [float(near.x), float(near.y)], "err": str(e)[:200]},
            )
            return None

    def _ensure_wall_slots_loaded(self, where: str) -> None:
        if self.wall is None:
            return
        w = str(where).strip().upper()
        if w not in self._wall_slots:
            return
        if self._wall_slots[w]["SUPPLYDEPOT"] or self._wall_slots[w]["BARRACKS"]:
            return

        try:
            depots = [p for p in self.wall.wall_spots_for(U.SUPPLYDEPOT, where=w) if p is not None]
            rax = [p for p in self.wall.wall_spots_for(U.BARRACKS, where=w) if p is not None]
            self._wall_slots[w]["SUPPLYDEPOT"] = [_snap_half(p) for p in depots[:2]]
            self._wall_slots[w]["BARRACKS"] = [_snap_half(p) for p in rax[:1]]
            self._emit(
                "placement_wall_slots_loaded",
                {
                    "where": w,
                    "depots": [[float(p.x), float(p.y)] for p in self._wall_slots[w]["SUPPLYDEPOT"]],
                    "barracks": [[float(p.x), float(p.y)] for p in self._wall_slots[w]["BARRACKS"]],
                },
            )
        except Exception:
            self._wall_slots[w]["SUPPLYDEPOT"] = []
            self._wall_slots[w]["BARRACKS"] = []

    def _my_units_of_type(self, ut: U) -> list[Any]:
        if not hasattr(self.bot, "units"):
            return []
        try:
            units = self.bot.units(ut)
        except Exception:
            return []
        out = []
        for u in units:
            is_mine = getattr(u, "is_mine", None)
            if is_mine is not None and not is_mine:
                continue
            out.append(u)
        return out

    def _occupied_near(self, ut: U, pos: Point2, *, max_d: float = 1.0) -> bool:
        for u in self._my_units_of_type(ut):
            try:
                if float(u.distance_to(pos)) <= float(max_d):
                    return True
            except Exception:
                continue
        return False

    async def _try_main_wall_firsts(self, ut: U) -> Optional[Point2]:
        """
        Força MAIN wall para:
          - SUPPLYDEPOT: usa os 2 slots disponíveis
          - BARRACKS: usa o 1 slot disponível
        Sem contador interno: decide por ocupação real + reserva TTL.
        """
        if not self.main_wall_enabled:
            return None
        if self.wall is None or not self.wall_main:
            return None
        if ut not in (U.SUPPLYDEPOT, U.BARRACKS):
            return None

        self._cleanup_reservations()
        self._ensure_wall_slots_loaded("MAIN")

        slots = self._wall_slots["MAIN"].get(ut.name, [])
        if not slots:
            return None

        for p in list(slots):
            p = _snap_half(p)

            if self._occupied_near(ut, p, max_d=1.0):
                continue
            if self._is_reserved(ut, p):
                continue
            if not await self._can_place(ut, p):
                continue

            self._reserve(ut, p)
            self._emit("placement_main_wall_forced", {"unit": ut.name, "pos": [float(p.x), float(p.y)]})
            return p

        return None

    def _cache_key(self, ut: U, near: Point2 | None) -> str:
        return f"{ut.name}@{_near_key(near)}"

    async def find_placement(
        self,
        unit_type,
        *,
        near: Point2 | None = None,
        wall_pref: str | None = None,
    ) -> Point2 | None:
        ut = unit_type
        if isinstance(unit_type, str):
            ut = getattr(U, unit_type)

        # se near não veio, assume MAIN estável
        if near is None:
            near = self._pick_main_anchor()

        # (A) wall_pref explícita (opener/force)
        if wall_pref is not None:
            w = str(wall_pref).strip().upper()
            self._cleanup_reservations()
            self._ensure_wall_slots_loaded(w)
            slots = self._wall_slots.get(w, {}).get(ut.name, [])
            for p in list(slots):
                p = _snap_half(p)

                if self._occupied_near(ut, p, max_d=1.0):
                    continue
                if self._is_reserved(ut, p):
                    continue
                if not await self._can_place(ut, p):
                    continue

                self._reserve(ut, p)
                self._cache[self._cache_key(ut, near)] = p
                self._emit("placement_wall_pick", {"where": w, "unit": ut.name, "pos": [float(p.x), float(p.y)]})
                return p

        # (B) primeiros buildings na MAIN wall
        forced = await self._try_main_wall_firsts(ut)
        if forced is not None:
            return forced

        # (C) fallback normal
        self._cleanup_reservations()

        ck = self._cache_key(ut, near)
        cached = self._cache.get(ck)
        if cached is not None and not self._is_reserved(ut, cached):
            # guarda: se cache “vazou” pra longe do near, ignora
            try:
                d = float(cached.distance_to(near))
            except Exception:
                d = 9999.0

            if d <= self.cache_max_dist:
                if await self._can_place(ut, cached):
                    self._reserve(ut, cached)
                    self._emit(
                        "placement_cache_hit",
                        {"unit": ut.name, "near": [float(near.x), float(near.y)], "pos": [float(cached.x), float(cached.y)], "d": d},
                    )
                    return cached
            else:
                self._emit(
                    "placement_cache_skip_far",
                    {
                        "unit": ut.name,
                        "near": [float(near.x), float(near.y)],
                        "cached": [float(cached.x), float(cached.y)],
                        "d": d,
                        "max": float(self.cache_max_dist),
                    },
                )

        pos = await self._fallback_find(ut, near=near)
        if pos is None:
            self._emit("placement_fail", {"unit": ut.name, "near": [float(near.x), float(near.y)]})
            return None

        pos = _snap_half(pos)
        self._reserve(ut, pos)
        self._cache[ck] = pos
        self._emit("placement_ok", {"unit": ut.name, "near": [float(near.x), float(near.y)], "pos": [float(pos.x), float(pos.y)]})
        return pos
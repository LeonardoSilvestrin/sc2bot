#bot/engine/wall.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, List

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2


def _snap_half(p: Point2) -> Point2:
    x = round(float(p.x) * 2.0) / 2.0
    y = round(float(p.y) * 2.0) / 2.0
    return Point2((x, y))


@dataclass
class WallLayout:
    ramp: Any
    ramp_center: Optional[Point2]
    depot_positions: List[Point2]
    barracks_position: Optional[Point2]


class WallPlanner:
    """
    Suporta 2 walls:
      - MAIN: usa main_base_ramp quando possível
      - NATURAL: rampa mais provável da natural

    Retorna spots (2 depots + 1 barracks quando disponíveis).
    """

    def __init__(self, bot: Any, *, ctx: Any, logger: Any | None = None, debug: bool = True):
        self.bot = bot
        self.ctx = ctx
        self.log = logger
        self.debug = debug

        self._cached_main: WallLayout | None = None
        self._cached_nat: WallLayout | None = None
        self._cached_main_iter: int = -999999
        self._cached_nat_iter: int = -999999

    def _emit(self, event: str, payload: dict) -> None:
        if self.log:
            self.log.emit(event, payload, meta={"iter": int(getattr(self.ctx, "iteration", 0))})

    def _my_start(self) -> Optional[Point2]:
        return getattr(self.bot, "start_location", None)

    def _enemy_main(self) -> Optional[Point2]:
        locs = getattr(self.bot, "enemy_start_locations", None)
        return locs[0] if locs else None

    def _expansions(self) -> list[Point2]:
        exps = getattr(self.bot, "expansion_locations_list", None)
        return list(exps) if exps else []

    def _my_main_expansion(self) -> Optional[Point2]:
        my_main = self._my_start()
        exps = self._expansions()
        if my_main is None or not exps:
            return None
        return min(exps, key=lambda p: p.distance_to(my_main))

    def _my_natural(self) -> Optional[Point2]:
        nat = getattr(self.bot, "cached_natural_expansion", None)
        if nat is not None:
            return nat
        main_exp = self._my_main_expansion()
        exps = self._expansions()
        if main_exp is None or not exps:
            return None
        candidates = [p for p in exps if p.distance_to(main_exp) > 3.0]
        if not candidates:
            return None
        return min(candidates, key=lambda p: p.distance_to(main_exp))

    def _iter_ramps(self) -> list[Any]:
        gi = getattr(self.bot, "game_info", None)
        ramps = getattr(gi, "map_ramps", None) if gi is not None else None
        if ramps is None:
            ramps = getattr(self.bot, "ramps", None)
        try:
            return list(ramps) if ramps else []
        except Exception:
            return []

    def _is_reasonable_ramp(self, r: Any) -> bool:
        if r is None:
            return False
        if getattr(r, "top_center", None) is None and getattr(r, "upper", None) is None:
            return False
        return True

    def _ramp_center(self, r: Any) -> Optional[Point2]:
        tc = getattr(r, "top_center", None)
        bc = getattr(r, "bottom_center", None)
        if tc is not None and bc is not None:
            try:
                return Point2(((tc.x + bc.x) / 2, (tc.y + bc.y) / 2))
            except Exception:
                pass
        for k in ("top_center", "bottom_center", "upper", "lower"):
            p = getattr(r, k, None)
            if p is not None:
                return p
        return None

    def _layout_from_ramp(self, ramp: Any, *, label: str) -> WallLayout | None:
        if ramp is None:
            return None

        center = self._ramp_center(ramp)
        if center is not None:
            center = _snap_half(center)

        depot_positions: List[Point2] = []
        barracks_pos: Optional[Point2] = None

        # Ramp helpers (quando existem) — sempre snap.
        try:
            cds = getattr(ramp, "corner_depots", None)
            if cds:
                depot_positions = [_snap_half(p) for p in list(cds)[:2] if p is not None]
        except Exception:
            depot_positions = []

        try:
            bcp = getattr(ramp, "barracks_correct_placement", None)
            if bcp is not None:
                barracks_pos = _snap_half(bcp)
        except Exception:
            barracks_pos = None

        self._emit(
            "wall_layout",
            {
                "where": label,
                "ramp_center": [float(center.x), float(center.y)] if center else None,
                "depot_positions": [[float(p.x), float(p.y)] for p in depot_positions],
                "barracks_position": [float(barracks_pos.x), float(barracks_pos.y)] if barracks_pos else None,
            },
        )

        return WallLayout(
            ramp=ramp,
            ramp_center=center,
            depot_positions=depot_positions,
            barracks_position=barracks_pos,
        )

    def _main_ramp(self) -> Any | None:
        return getattr(self.bot, "main_base_ramp", None)

    def _find_natural_ramp(self) -> Any | None:
        nat = self._my_natural()
        if nat is None:
            return None

        enemy = self._enemy_main()
        ramps = [r for r in self._iter_ramps() if self._is_reasonable_ramp(r)]
        if not ramps:
            return None

        main_ramp = self._main_ramp()
        if main_ramp is not None:
            ramps = [r for r in ramps if r is not main_ramp]

        if not ramps:
            return None

        def score(r: Any) -> float:
            c = self._ramp_center(r)
            if c is None:
                return 1e18
            d_nat = float(c.distance_to(nat))
            if enemy is None:
                return d_nat
            d_enemy = float(c.distance_to(enemy))
            return d_nat + 0.03 * d_enemy

        return min(ramps, key=score)

    def compute(self, where: str, *, cache_window_iters: int = 400) -> WallLayout | None:
        it = int(getattr(self.ctx, "iteration", 0))
        w = str(where).strip().upper()

        if w == "MAIN":
            if self._cached_main is not None and (it - self._cached_main_iter) <= int(cache_window_iters):
                return self._cached_main

            ramp = self._main_ramp()
            layout = self._layout_from_ramp(ramp, label="MAIN")
            self._cached_main = layout
            self._cached_main_iter = it
            return layout

        if w == "NATURAL":
            if self._cached_nat is not None and (it - self._cached_nat_iter) <= int(cache_window_iters):
                return self._cached_nat

            ramp = self._find_natural_ramp()
            layout = self._layout_from_ramp(ramp, label="NATURAL")
            self._cached_nat = layout
            self._cached_nat_iter = it
            return layout

        return None

    def wall_spots_for(self, unit_type: U, *, where: str) -> List[Point2]:
        layout = self.compute(where)
        if layout is None:
            return []
        if unit_type == U.SUPPLYDEPOT:
            return list(layout.depot_positions)[:2]
        if unit_type == U.BARRACKS:
            return [layout.barracks_position] if layout.barracks_position is not None else []
        return []

    def wall_anchor(self, *, where: str) -> Optional[Point2]:
        layout = self.compute(where)
        if layout is None:
            return None
        return layout.ramp_center
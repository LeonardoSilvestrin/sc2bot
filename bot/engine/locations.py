#bot/engine/locations.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

from sc2.position import Point2
from sc2.ids.unit_typeid import UnitTypeId as U

from bot.engine.expansion_finder import compute_main_and_natural


def _k(p: Point2) -> Tuple[int, int]:
    return (int(round(float(p.x) * 2)), int(round(float(p.y) * 2)))


@dataclass
class MapLocations:
    my_main: Optional[Point2] = None
    my_natural: Optional[Point2] = None
    enemy_main: Optional[Point2] = None
    enemy_natural: Optional[Point2] = None


class LocationsService:
    """
    Fonte única da verdade para:
      - my_main / my_natural
      - enemy_main / enemy_natural

    Critério: distância de CHÃO.
    Sem fallback silencioso pra euclidiana.
    """

    def __init__(self, bot: Any, *, ctx: Any, logger: Any | None = None, debug: bool = True):
        self.bot = bot
        self.ctx = ctx
        self.log = logger
        self.debug = debug

        self.loc = MapLocations()

        self._cache_my: Dict[Tuple[int, int], float] = {}
        self._cache_enemy: Dict[Tuple[int, int], float] = {}

        self._next_recalc_iter: int = 0
        self._last_emit_iter: int = -999999

    # -----------------------
    # Legacy API (compat)
    # -----------------------
    def my_main_exp(self) -> Optional[Point2]:
        return self.loc.my_main

    def my_natural_exp(self) -> Optional[Point2]:
        return self.loc.my_natural

    def enemy_main_exp(self) -> Optional[Point2]:
        return self.loc.enemy_main

    def enemy_natural_exp(self) -> Optional[Point2]:
        return self.loc.enemy_natural

    # -----------------------
    # Internals
    # -----------------------
    def _emit(self, event: str, payload: dict) -> None:
        if self.log:
            self.log.emit(event, payload, meta={"iter": int(getattr(self.ctx, "iteration", 0))})

    def _expansions(self) -> List[Point2]:
        exps = getattr(self.bot, "expansion_locations_list", None)
        return list(exps) if exps else []

    def _pt(self, p: Optional[Point2]) -> Optional[list[float]]:
        if p is None:
            return None
        return [float(p.x), float(p.y)]

    def _same(self, a: Optional[Point2], b: Optional[Point2], eps: float = 0.25) -> bool:
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        return float(a.distance_to(b)) <= float(eps)

    # ---- START ORIGINS (sem euclidiano) ----
    def _my_ground_start(self) -> Optional[Point2]:
        """
        Prioridade:
        1) centro do townhall (muito melhor pro pathing do que start_location)
        2) SCV (se por algum motivo não tem townhall)
        3) start_location (último recurso)
        """
        ths = getattr(self.bot, "townhalls", None)
        if ths is not None:
            try:
                if ths.ready:
                    return ths.ready.first.position
            except Exception:
                pass
            try:
                if ths:
                    return ths.first.position
            except Exception:
                pass

        workers = getattr(self.bot, "workers", None)
        if workers is not None:
            try:
                if workers:
                    return workers.first.position
            except Exception:
                pass

        return getattr(self.bot, "start_location", None)

    def _enemy_ground_start(self) -> Optional[Point2]:
        """
        Prioridade:
        1) inimigo visto: CC/Nexus/Hatch/Lair/Hive etc
        2) enemy_start_locations[0]
        """
        # enemy structures seen (quando tiver)
        try:
            es = getattr(self.bot, "enemy_structures", None)
            if es is not None:
                for ut in (U.COMMANDCENTER, U.ORBITALCOMMAND, U.PLANETARYFORTRESS, U.NEXUS, U.HATCHERY, U.LAIR, U.HIVE):
                    try:
                        grp = es(ut)
                        if grp:
                            # pega o mais “central”/primeiro
                            return grp.first.position
                    except Exception:
                        continue
        except Exception:
            pass

        locs = getattr(self.bot, "enemy_start_locations", None)
        return locs[0] if locs else None

    async def recalc_if_needed(self, iteration: int, *, every_iters: int = 110) -> None:
        iteration = int(iteration)
        if iteration < int(self._next_recalc_iter):
            return

        exps = self._expansions()
        if not exps:
            return

        my_start = self._my_ground_start()
        enemy_start = self._enemy_ground_start()

        # se nem start temos, não inventa
        if my_start is None:
            self._emit("locations_skip", {"reason": "no_my_start"})
            self._next_recalc_iter = iteration + int(every_iters)
            return

        # --- MY ---
        my_main, my_nat = await compute_main_and_natural(
            self.bot, expansions=exps, start=my_start, cache=self._cache_my
        )

        # --- ENEMY ---
        enemy_main, enemy_nat = (None, None)
        if enemy_start is not None:
            enemy_main, enemy_nat = await compute_main_and_natural(
                self.bot, expansions=exps, start=enemy_start, cache=self._cache_enemy
            )

        # se enemy_start não existe ainda, não chuta
        changed = (
            (not self._same(self.loc.my_main, my_main))
            or (not self._same(self.loc.my_natural, my_nat))
            or (not self._same(self.loc.enemy_main, enemy_main))
            or (not self._same(self.loc.enemy_natural, enemy_nat))
        )

        self.loc.my_main = my_main
        self.loc.my_natural = my_nat
        self.loc.enemy_main = enemy_main
        self.loc.enemy_natural = enemy_nat

        # publica também no bot (compat)
        self.bot.cached_main_expansion = my_main
        self.bot.cached_natural_expansion = my_nat
        self.bot.cached_enemy_main_expansion = enemy_main
        self.bot.cached_enemy_natural_expansion = enemy_nat

        # loga origem usada (pra debug do “ponto errado”)
        if self.log:
            self._emit(
                "locations_origin",
                {
                    "my_start": self._pt(my_start),
                    "enemy_start": self._pt(enemy_start),
                },
            )

        # emite evento: no máximo 1x por ~22 iters, ou sempre se mudou
        if changed or (iteration - self._last_emit_iter) >= 22:
            self._last_emit_iter = iteration
            self._emit(
                "locations_update",
                {
                    "my_main": self._pt(my_main),
                    "my_natural": self._pt(my_nat),
                    "enemy_main": self._pt(enemy_main),
                    "enemy_natural": self._pt(enemy_nat),
                },
            )

        self._next_recalc_iter = iteration + int(every_iters)
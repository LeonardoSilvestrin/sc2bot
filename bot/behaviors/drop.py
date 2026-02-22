from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

import inspect
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.ability_id import AbilityId as A
from sc2.position import Point2

from .base import TickBudget


class DropPhase(str, Enum):
    WAIT = "wait"
    PICKUP = "pickup"  # aproxima do pickup antes de tentar LOAD
    LOAD = "load"
    MOVE = "move"
    DROP = "drop"
    FIGHT = "fight"
    DONE = "done"


@dataclass
class DropRuntime:
    phase: DropPhase = DropPhase.WAIT
    medivac_tag: Optional[int] = None
    pickup: Optional[Point2] = None
    staging: Optional[Point2] = None
    target: Optional[Point2] = None
    next_loop: int = 0


class DropBehavior:
    name = "drop"

    def __init__(self, bot: Any, ctx: Any, logger: Any | None = None, debug: bool = True):
        self.bot = bot
        self.ctx = ctx
        self.log = logger
        self.debug = debug
        self.rt = DropRuntime()

    # ----------------------------
    # helpers
    # ----------------------------
    def _loop(self) -> int:
        st = getattr(self.bot, "state", None)
        gl = getattr(st, "game_loop", None)
        if gl is not None:
            return int(gl)
        it = getattr(self.ctx, "iteration", None)
        return int(it) if it is not None else 0

    def _time(self) -> float:
        t = getattr(self.bot, "time", None)
        try:
            return float(t)
        except Exception:
            return 0.0

    def _emit(self, event: str, payload: dict):
        if self.log:
            self.log.emit(event, payload, meta={"iter": int(getattr(self.ctx, "iteration", 0))})

    # ----------------------------
    # claims (shared between drop instances via ctx)
    # ----------------------------
    def _claims(self) -> dict:
        c = getattr(self.ctx, "claims", None)
        if not isinstance(c, dict):
            c = {}
            setattr(self.ctx, "claims", c)
        c.setdefault("medivac_by_drop", {})   # drop_id -> medivac_tag
        c.setdefault("marine_by_drop", {})    # drop_id -> set[marine_tag]
        c.setdefault("owner_by_unit", {})     # unit_tag -> drop_id
        return c

    def _drop_id(self, drop_cfg) -> str:
        return str(getattr(drop_cfg, "name", "drop")).strip() or "drop"

    def _unit_owner(self, tag: int) -> Optional[str]:
        return self._claims()["owner_by_unit"].get(int(tag))

    def _claim_unit(self, drop_id: str, tag: int):
        self._claims()["owner_by_unit"][int(tag)] = drop_id

    def _release_unit(self, tag: int):
        self._claims()["owner_by_unit"].pop(int(tag), None)

    def _release_drop_marines(self, drop_id: str):
        claims = self._claims()
        tags = claims["marine_by_drop"].get(drop_id, set())
        for t in list(tags):
            if claims["owner_by_unit"].get(int(t)) == drop_id:
                claims["owner_by_unit"].pop(int(t), None)
        claims["marine_by_drop"][drop_id] = set()

    def _release_drop_medivac(self, drop_id: str):
        claims = self._claims()
        tag = claims["medivac_by_drop"].pop(drop_id, None)
        if tag is None:
            return
        if claims["owner_by_unit"].get(int(tag)) == drop_id:
            claims["owner_by_unit"].pop(int(tag), None)

    # ----------------------------
    # command bridge (awaitable or sync)
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
    # points
    # ----------------------------
    def _enemy_main(self) -> Optional[Point2]:
        locs = getattr(self.bot, "enemy_start_locations", None)
        return locs[0] if locs else None

    def _my_start(self) -> Optional[Point2]:
        return getattr(self.bot, "start_location", None)

    def _expansions(self) -> list[Point2]:
        exps = getattr(self.bot, "expansion_locations_list", None)
        return list(exps) if exps else []

    def _enemy_main_expansion(self) -> Optional[Point2]:
        enemy_main = self._enemy_main()
        exps = self._expansions()
        if enemy_main is None or not exps:
            return None
        return min(exps, key=lambda p: p.distance_to(enemy_main))

    def _enemy_natural(self) -> Optional[Point2]:
        main_exp = self._enemy_main_expansion()
        exps = self._expansions()
        if main_exp is None or not exps:
            return None
        candidates = [p for p in exps if p.distance_to(main_exp) > 3.0]
        if not candidates:
            return None
        return min(candidates, key=lambda p: p.distance_to(main_exp))

    def _my_main_expansion(self) -> Optional[Point2]:
        my_main = self._my_start()
        exps = self._expansions()
        if my_main is None or not exps:
            return None
        return min(exps, key=lambda p: p.distance_to(my_main))

    def _my_natural(self) -> Optional[Point2]:
        main_exp = self._my_main_expansion()
        exps = self._expansions()
        if main_exp is None or not exps:
            return None
        candidates = [p for p in exps if p.distance_to(main_exp) > 3.0]
        if not candidates:
            return None
        return min(candidates, key=lambda p: p.distance_to(main_exp))

    def _point_by_key(self, key: str) -> Optional[Point2]:
        if key == "ENEMY_MAIN":
            return self._enemy_main()
        if key == "ENEMY_NATURAL":
            return self._enemy_natural()
        if key == "MY_MAIN":
            return self._my_start()
        if key == "MY_NATURAL":
            return self._my_natural()
        return None

    def _resolve_points(self, drop_cfg) -> tuple[Optional[Point2], Optional[Point2], Optional[Point2]]:
        enemy_main = self._enemy_main()
        my_main = self._my_start()
        if enemy_main is None or my_main is None:
            return None, None, None

        pickup_key = str(getattr(drop_cfg, "pickup", None) or "MY_MAIN")
        staging_key = str(getattr(drop_cfg, "staging", None) or "ENEMY_NATURAL")
        target_key = str(getattr(drop_cfg, "target", None) or "ENEMY_MAIN")

        pickup = self._point_by_key(pickup_key)
        staging_anchor = self._point_by_key(staging_key)
        target = self._point_by_key(target_key)

        if pickup is None or staging_anchor is None or target is None:
            return None, None, None

        dist = float(getattr(drop_cfg, "staging_dist", 18.0))
        staging = staging_anchor.towards(my_main, dist)
        return pickup, staging, target

    # ----------------------------
    # resource selection
    # ----------------------------
    def _pick_medivac_for(self, drop_id: str) -> Optional[Any]:
        meds = self.bot.units(U.MEDIVAC) if hasattr(self.bot, "units") else None
        if not meds:
            return None

        claims = self._claims()
        med_by_drop = claims["medivac_by_drop"]

        claimed_tag = med_by_drop.get(drop_id)
        if claimed_tag is not None:
            m = meds.find_by_tag(int(claimed_tag))
            if m:
                self.rt.medivac_tag = int(m.tag)
                return m
            # morreu/sumiu
            med_by_drop.pop(drop_id, None)
            if self._unit_owner(int(claimed_tag)) == drop_id:
                self._release_unit(int(claimed_tag))

        ready = meds.ready if hasattr(meds, "ready") else meds
        if not ready:
            return None

        for m in ready:
            tag = int(m.tag)
            if self._unit_owner(tag) is None:
                med_by_drop[drop_id] = tag
                self._claim_unit(drop_id, tag)
                self.rt.medivac_tag = tag
                return m

        return None

    def _pick_marine_for(self, drop_id: str, med, *, max_range: float) -> Optional[Any]:
        marines = self.bot.units(U.MARINE) if hasattr(self.bot, "units") else None
        if not marines:
            return None
        marines_ready = marines.ready if hasattr(marines, "ready") else marines
        if not marines_ready:
            return None

        claims = self._claims()
        claims["marine_by_drop"].setdefault(drop_id, set())

        best = None
        best_d = 1e18
        for m in marines_ready:
            tag = int(m.tag)
            if self._unit_owner(tag) is not None:
                continue
            d = m.distance_to(med)
            if d <= max_range and d < best_d:
                best = m
                best_d = d

        if best is None:
            return None

        t = int(best.tag)
        self._claim_unit(drop_id, t)
        claims["marine_by_drop"][drop_id].add(t)
        return best

    def _count_free_marines(self) -> int:
        marines = self.bot.units(U.MARINE) if hasattr(self.bot, "units") else None
        if not marines:
            return 0
        marines_ready = marines.ready if hasattr(marines, "ready") else marines
        if not marines_ready:
            return 0
        free = 0
        for m in marines_ready:
            if self._unit_owner(int(m.tag)) is None:
                free += 1
        return free

    async def _nudge_marines_to_pickup(self, pickup: Point2, *, max_orders: int = 1) -> int:
        """
        Opcional mas MUITO útil:
        - puxa marines antigos/espalhados para o pickup, evitando o medivac ficar no vazio.
        - 1 comando por tick (default) pra não spammar.
        """
        marines = self.bot.units(U.MARINE) if hasattr(self.bot, "units") else None
        if not marines:
            return 0
        marines_ready = marines.ready if hasattr(marines, "ready") else marines
        if not marines_ready:
            return 0

        issued = 0
        # pega marines idle e longe
        candidates = [m for m in marines_ready if getattr(m, "is_idle", False) and m.distance_to(pickup) > 8]
        # move os mais longe primeiro (tende a convergir)
        candidates.sort(key=lambda m: m.distance_to(pickup), reverse=True)

        for m in candidates[:max_orders]:
            ok = await self._do(m.move(pickup))
            if ok:
                issued += 1
            else:
                break
        return issued

    # ----------------------------
    # main
    # ----------------------------
    async def step(self, budget: TickBudget, cfg: dict) -> bool:
        drop_cfg = cfg["drop"]
        if not drop_cfg.enabled:
            return False

        drop_id = self._drop_id(drop_cfg)
        loop = self._loop()

        if loop < self.rt.next_loop or budget.remaining <= 0:
            return False

        # ---- schedule gate ----
        start_loop = getattr(drop_cfg, "start_loop", None)
        start_time = getattr(drop_cfg, "start_time", None)

        if self.rt.phase == DropPhase.WAIT:
            if start_loop is not None and loop < int(start_loop):
                self._emit(
                    "drop_wait",
                    {"drop": drop_id, "reason": "waiting_start_loop", "now": loop, "start_loop": int(start_loop)},
                )
                self.rt.next_loop = loop + 12
                return False
            if start_time is not None and self._time() < float(start_time):
                self._emit(
                    "drop_wait",
                    {"drop": drop_id, "reason": "waiting_start_time", "now": self._time(), "start_time": float(start_time)},
                )
                self.rt.next_loop = loop + 12
                return False

        # resolve points (1x)
        if self.rt.pickup is None or self.rt.staging is None or self.rt.target is None:
            pickup, staging, target = self._resolve_points(drop_cfg)
            self.rt.pickup, self.rt.staging, self.rt.target = pickup, staging, target
            if pickup is None or staging is None or target is None:
                self._emit("drop_wait", {"drop": drop_id, "reason": "no_points"})
                self.rt.next_loop = loop + 12
                return False

        min_marines = int(getattr(drop_cfg, "min_marines", 8))
        load_count = int(getattr(drop_cfg, "load_count", min_marines))
        move_eps = float(getattr(drop_cfg, "move_eps", 3.0))
        pickup_eps = float(getattr(drop_cfg, "pickup_eps", 6.0))
        load_max_range = float(getattr(drop_cfg, "load_range", 7.0))

        # pega medivac (claimado ou novo)
        med = self._pick_medivac_for(drop_id)
        if med is None:
            self._emit("drop_wait", {"drop": drop_id, "reason": "no_medivac"})
            self.rt.next_loop = loop + 12
            return False

        # gate melhor: se está no WAIT, garanta marines LIVRES suficientes (sincroniza melhor em multi-drop)
        if self.rt.phase == DropPhase.WAIT:
            free = self._count_free_marines()
            if free < min_marines:
                self._emit(
                    "drop_wait",
                    {"drop": drop_id, "reason": "not_enough_free_marines", "free": int(free), "need": int(min_marines)},
                )
                self.rt.next_loop = loop + 12
                return False

        # ----------------------------
        # state machine
        # ----------------------------
        if self.rt.phase == DropPhase.WAIT:
            self._emit(
                "drop_armed",
                {"drop": drop_id, "min_marines": min_marines, "load_count": load_count, "medivac_tag": int(med.tag)},
            )
            self.rt.phase = DropPhase.PICKUP
            self.rt.next_loop = loop + 1
            return False

        if self.rt.phase == DropPhase.PICKUP:
            # puxa marines ao pickup (ajuda muito com "marines antigos" espalhados)
            if budget.remaining > 0:
                issued = await self._nudge_marines_to_pickup(self.rt.pickup, max_orders=1)
                if issued > 0:
                    budget.remaining -= 1
                    self._emit("drop_pickup_nudge", {"drop": drop_id, "issued": int(issued)})

            # garante medivac no pickup
            if med.distance_to(self.rt.pickup) <= pickup_eps:
                self._emit("drop_at_pickup", {"drop": drop_id, "pickup": [float(self.rt.pickup.x), float(self.rt.pickup.y)]})
                self.rt.phase = DropPhase.LOAD
                self.rt.next_loop = loop + 1
                return issued > 0  # se nudged, consumiu action

            ok = await self._do(med.move(self.rt.pickup))
            if ok:
                budget.remaining -= 1
                self._emit("drop_pickup_move", {"drop": drop_id, "to": [float(self.rt.pickup.x), float(self.rt.pickup.y)]})
                self.rt.next_loop = loop + 8
                return True

            self.rt.next_loop = loop + 8
            return False

        if self.rt.phase == DropPhase.LOAD:
            # tenta carregar 1 por tick (coop com RR)
            m = self._pick_marine_for(drop_id, med, max_range=load_max_range)
            if m is None:
                # se não tem marine em range, reposiciona e/ou espera sem spam
                if med.distance_to(self.rt.pickup) > pickup_eps:
                    ok = await self._do(med.move(self.rt.pickup))
                    if ok:
                        budget.remaining -= 1
                        self._emit("drop_loading_reposition", {"drop": drop_id, "to_pickup": True})
                        self.rt.next_loop = loop + 8
                        return True

                self._emit(
                    "drop_loading",
                    {"drop": drop_id, "reason": "no_free_marine_in_range", "range": float(load_max_range)},
                )
                self.rt.next_loop = loop + 6
                return False

            dist = float(m.distance_to(med))
            ok = await self._do(med(A.LOAD, m))
            if ok:
                budget.remaining -= 1
            else:
                # se falhou, libera o marine (provavelmente range/estado)
                self._release_unit(int(m.tag))

            cargo_used = int(getattr(med, "cargo_used", 0))
            self._emit(
                "drop_loading",
                {"drop": drop_id, "cargo_used": cargo_used, "target": load_count, "picked_dist": dist, "ok": bool(ok)},
            )

            if cargo_used >= load_count:
                self._emit("drop_loaded", {"drop": drop_id, "cargo_used": cargo_used})
                self.rt.phase = DropPhase.MOVE
                self.rt.next_loop = loop + 1
                return True

            self.rt.next_loop = loop + 4
            return True

        if self.rt.phase == DropPhase.MOVE:
            if med.distance_to(self.rt.staging) <= move_eps:
                self._emit("drop_at_staging", {"drop": drop_id, "pos": [float(med.position.x), float(med.position.y)]})
                self.rt.phase = DropPhase.DROP
                self.rt.next_loop = loop + 1
                return False

            ok = await self._do(med.move(self.rt.staging))
            if ok:
                budget.remaining -= 1
                self._emit("drop_move", {"drop": drop_id, "to": [float(self.rt.staging.x), float(self.rt.staging.y)]})
                self.rt.next_loop = loop + 8
                return True

            self.rt.next_loop = loop + 8
            return False

        if self.rt.phase == DropPhase.DROP:
            if med.distance_to(self.rt.target) > move_eps * 2:
                ok = await self._do(med.move(self.rt.target))
                if ok:
                    budget.remaining -= 1
                    self._emit("drop_approach", {"drop": drop_id, "to": [float(self.rt.target.x), float(self.rt.target.y)]})
                    self.rt.next_loop = loop + 8
                    return True
                self.rt.next_loop = loop + 8
                return False

            ok = await self._do(med(A.UNLOADALLAT, self.rt.target))
            if ok:
                budget.remaining -= 1
                self._emit("drop_unload", {"drop": drop_id, "at": [float(self.rt.target.x), float(self.rt.target.y)]})

                # libera marines após unload (senão outro drop pode travar)
                self._release_drop_marines(drop_id)

                # libera medivac também (evita “prisão eterna” do medivac no drop)
                self._release_drop_medivac(drop_id)

                self.rt.phase = DropPhase.FIGHT
                self.rt.next_loop = loop + 6
                return True

            self.rt.next_loop = loop + 6
            return False

        if self.rt.phase == DropPhase.FIGHT:
            # aqui você ainda não está fazendo stim (isso depende de research/upgrades)
            # então deixo só o ataque simples.
            ground = self.bot.units(U.MARINE) if hasattr(self.bot, "units") else None
            if ground and ground.amount > 0:
                for mm in ground:
                    if budget.remaining <= 0:
                        break
                    if mm.distance_to(self.rt.target) < 15 and getattr(mm, "is_idle", True):
                        ok = await self._do(mm.attack(self.rt.target))
                        if ok:
                            budget.remaining -= 1
                            self._emit("drop_attack", {"drop": drop_id, "target": [float(self.rt.target.x), float(self.rt.target.y)]})
                            self.rt.next_loop = loop + 10
                            self.rt.phase = DropPhase.DONE
                            return True

            self.rt.next_loop = loop + 12
            self.rt.phase = DropPhase.DONE
            return False

        if self.rt.phase == DropPhase.DONE:
            return False

        return False
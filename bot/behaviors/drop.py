#bot/behaviors/drop.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, List

import inspect

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.ability_id import AbilityId as A
from sc2.position import Point2

from .base import TickBudget


class DropPhase(str, Enum):
    WAIT = "wait"
    PREP = "prep"
    LOAD = "load"
    MOVE = "move"
    DROP = "drop"
    FIGHT = "fight"
    DONE = "done"


@dataclass
class DropRuntime:
    phase: DropPhase = DropPhase.WAIT
    pickup: Optional[Point2] = None
    staging: Optional[Point2] = None
    target: Optional[Point2] = None
    next_loop: int = 0

    medivac_tag: Optional[int] = None
    marine_tags: List[int] = None

    fight_until_time: float = 0.0

    def __post_init__(self):
        if self.marine_tags is None:
            self.marine_tags = []


class DropBehavior:
    """
    Identidade estável:
      - cada instância recebe drop_id (tipicamente DropCfg.name)
      - owner = f"drop:{drop_id}" NÃO depende do cfg recebido no step()
    """
    name = "drop"

    def __init__(
        self,
        bot: Any,
        ctx: Any,
        unit_manager: Any,
        *,
        drop_id: str,
        logger: Any | None = None,
        debug: bool = True,
    ):
        self.bot = bot
        self.ctx = ctx
        self.um = unit_manager
        self.log = logger
        self.debug = debug

        self.drop_id = (str(drop_id).strip() or "drop").replace(" ", "_")
        self.owner = f"drop:{self.drop_id}"

        # chave estável pro orchestrator
        self.key = self.drop_id

        self.rt = DropRuntime()

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
            meta = {"iter": int(getattr(self.ctx, "iteration", 0)), "drop": self.owner}
            self.log.emit(event, payload, meta=meta)

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

    # -------- points --------
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

    def _alive_medivac(self, tag: int):
        meds = self.bot.units(U.MEDIVAC) if hasattr(self.bot, "units") else None
        if not meds:
            return None
        return meds.find_by_tag(int(tag))

    def _alive_marine(self, tag: int):
        ms = self.bot.units(U.MARINE) if hasattr(self.bot, "units") else None
        if not ms:
            return None
        return ms.find_by_tag(int(tag))

    async def step(self, budget: TickBudget, cfg: dict) -> bool:
        drop_cfg = cfg["drop"]
        if not drop_cfg.enabled:
            return False

        loop = self._loop()
        if loop < self.rt.next_loop or budget.remaining <= 0:
            return False

        start_loop = getattr(drop_cfg, "start_loop", None)
        start_time = getattr(drop_cfg, "start_time", None)

        if self.rt.phase == DropPhase.WAIT:
            if start_loop is not None and loop < int(start_loop):
                self._emit("drop_wait", {"reason": "waiting_start_loop", "start_loop": int(start_loop)})
                self.rt.next_loop = loop + 12
                return False
            if start_time is not None and self._time() < float(start_time):
                self._emit("drop_wait", {"reason": "waiting_start_time", "start_time": float(start_time)})
                self.rt.next_loop = loop + 12
                return False

        if self.rt.pickup is None or self.rt.staging is None or self.rt.target is None:
            pickup, staging, target = self._resolve_points(drop_cfg)
            self.rt.pickup, self.rt.staging, self.rt.target = pickup, staging, target
            if pickup is None or staging is None or target is None:
                self._emit("drop_wait", {"reason": "no_points"})
                self.rt.next_loop = loop + 12
                return False

        min_marines = int(getattr(drop_cfg, "min_marines", 8))
        load_count = int(getattr(drop_cfg, "load_count", min_marines))
        move_eps = float(getattr(drop_cfg, "move_eps", 3.0))
        pickup_eps = float(getattr(drop_cfg, "pickup_eps", 6.0))
        load_range = float(getattr(drop_cfg, "load_range", 7.0))

        hard_gather = False
        if start_time is not None:
            hard_gather = (self._time() >= float(start_time) - 25.0)

        marine_select_maxd = float(getattr(drop_cfg, "marine_select_maxd", 120.0))
        gather_radius = float(getattr(drop_cfg, "gather_radius", max(14.0, pickup_eps + 8.0)))

        if self.rt.phase == DropPhase.WAIT:
            self._emit("drop_armed", {"load_count": int(load_count), "gather_radius": float(gather_radius)})
            self.rt.phase = DropPhase.PREP
            self.rt.next_loop = loop + 1
            return False

        if self.rt.phase == DropPhase.PREP:
            group = await self.um.request_group(
                owner=self.owner,
                pickup=self.rt.pickup,
                requirements={U.MEDIVAC: 1, U.MARINE: int(load_count)},
                soft_gather=True,
                hard_gather=hard_gather,
                gather_radius=gather_radius,
                max_distance_by_type={U.MARINE: marine_select_maxd},
            )

            if not group.ready:
                self._emit("drop_prep", {"ready": False})
                self.rt.next_loop = loop + 10
                return False

            med_tags = group.assigned.get(U.MEDIVAC, [])
            mar_tags = group.assigned.get(U.MARINE, [])
            if not med_tags or len(mar_tags) < load_count:
                self._emit("drop_prep", {"ready": False, "reason": "incomplete"})
                self.rt.next_loop = loop + 10
                return False

            med = self._alive_medivac(int(med_tags[0]))
            if med is None:
                self._emit("drop_prep", {"ready": False, "reason": "medivac_missing"})
                self.um.release_owner(self.owner)
                self.rt.next_loop = loop + 10
                return False

            self.rt.medivac_tag = int(med.tag)
            self.rt.marine_tags = [int(x) for x in mar_tags]

            if float(med.distance_to(self.rt.pickup)) > float(pickup_eps):
                ok = await self._do(med.move(self.rt.pickup))
                if ok:
                    budget.remaining -= 1
                    self._emit("drop_pickup_move", {"medivac_tag": int(med.tag)})
                    self.rt.next_loop = loop + 8
                    return True
                self.rt.next_loop = loop + 8
                return False

            self._emit(
                "drop_ready_to_load",
                {
                    "medivac_tag": int(med.tag),
                    "marines": int(len(self.rt.marine_tags)),
                    "marine_select_maxd": float(marine_select_maxd),
                    "gather_radius": float(gather_radius),
                },
            )
            self.rt.phase = DropPhase.LOAD
            self.rt.next_loop = loop + 1
            return False

        if self.rt.phase == DropPhase.LOAD:
            med = self._alive_medivac(int(self.rt.medivac_tag or -1))
            if med is None:
                self._emit("drop_abort", {"reason": "medivac_dead"})
                self.um.release_owner(self.owner)
                self.rt.phase = DropPhase.DONE
                return False

            if float(med.distance_to(self.rt.pickup)) > float(pickup_eps):
                ok = await self._do(med.move(self.rt.pickup))
                if ok:
                    budget.remaining -= 1
                    self._emit("drop_loading_reposition", {})
                    self.rt.next_loop = loop + 8
                    return True
                self.rt.next_loop = loop + 8
                return False

            cargo_used = int(getattr(med, "cargo_used", 0))
            if cargo_used >= load_count:
                self._emit("drop_loaded", {"cargo_used": int(cargo_used)})
                self.rt.phase = DropPhase.MOVE
                self.rt.next_loop = loop + 1
                return False

            best = None
            best_d = 1e18
            for t in list(self.rt.marine_tags):
                m = self._alive_marine(int(t))
                if not m:
                    try:
                        self.rt.marine_tags.remove(int(t))
                    except Exception:
                        pass
                    continue
                d = float(m.distance_to(med))
                if d < best_d:
                    best = m
                    best_d = d

            if best is None:
                self._emit("drop_loading", {"reason": "no_reserved_alive"})
                self.um.release_owner(self.owner)
                self.rt.phase = DropPhase.DONE
                return False

            if best_d > float(load_range):
                ok = await self._do(best.move(self.rt.pickup))
                if ok:
                    budget.remaining -= 1
                    self._emit("drop_call_marine", {"marine": int(best.tag), "dist": float(best_d)})
                    self.rt.next_loop = loop + 6
                    return True
                self.rt.next_loop = loop + 6
                return False

            ok = await self._do(med(A.LOAD, best))
            if ok:
                budget.remaining -= 1
            self._emit("drop_loading", {"marine": int(best.tag), "ok": bool(ok)})
            self.rt.next_loop = loop + 4
            return bool(ok)

        if self.rt.phase == DropPhase.MOVE:
            med = self._alive_medivac(int(self.rt.medivac_tag or -1))
            if med is None:
                self._emit("drop_abort", {"reason": "medivac_dead_move"})
                self.um.release_owner(self.owner)
                self.rt.phase = DropPhase.DONE
                return False

            if float(med.distance_to(self.rt.staging)) <= float(move_eps):
                self._emit("drop_at_staging", {})
                self.rt.phase = DropPhase.DROP
                self.rt.next_loop = loop + 1
                return False

            ok = await self._do(med.move(self.rt.staging))
            if ok:
                budget.remaining -= 1
                self._emit("drop_move", {})
                self.rt.next_loop = loop + 8
                return True
            self.rt.next_loop = loop + 8
            return False

        if self.rt.phase == DropPhase.DROP:
            med = self._alive_medivac(int(self.rt.medivac_tag or -1))
            if med is None:
                self._emit("drop_abort", {"reason": "medivac_dead_drop"})
                self.um.release_owner(self.owner)
                self.rt.phase = DropPhase.DONE
                return False

            if float(med.distance_to(self.rt.target)) > float(move_eps) * 2:
                ok = await self._do(med.move(self.rt.target))
                if ok:
                    budget.remaining -= 1
                    self._emit("drop_approach", {})
                    self.rt.next_loop = loop + 8
                    return True
                self.rt.next_loop = loop + 8
                return False

            ok = await self._do(med(A.UNLOADALLAT, self.rt.target))
            if ok:
                budget.remaining -= 1
                self._emit("drop_unload", {"target": [float(self.rt.target.x), float(self.rt.target.y)]})

                # libera APENAS o medivac
                if self.rt.medivac_tag is not None:
                    self.um.release_tags(self.owner, [int(self.rt.medivac_tag)])

                self.rt.fight_until_time = float(self._time()) + 18.0
                self.rt.phase = DropPhase.FIGHT
                self.rt.next_loop = loop + 2
                return True

            self.rt.next_loop = loop + 6
            return False

        if self.rt.phase == DropPhase.FIGHT:
            issued = 0
            for t in list(self.rt.marine_tags):
                if budget.remaining <= 0:
                    break
                m = self._alive_marine(int(t))
                if not m:
                    continue
                if bool(getattr(m, "is_idle", True)) and float(m.distance_to(self.rt.target)) < 20.0:
                    ok = await self._do(m.attack(self.rt.target))
                    if ok:
                        budget.remaining -= 1
                        issued += 1

            if issued > 0:
                self._emit("drop_attack", {"issued": int(issued)})
                self.rt.next_loop = loop + 8
                return True

            if float(self._time()) >= float(self.rt.fight_until_time):
                self._emit("drop_fight_done", {})
                self.um.release_owner(self.owner)
                self.rt.phase = DropPhase.DONE
                return False

            self.rt.next_loop = loop + 10
            return False

        return False
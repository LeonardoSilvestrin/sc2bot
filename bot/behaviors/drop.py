from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.ability_id import AbilityId as A
from sc2.position import Point2
import inspect
from .base import TickBudget


class DropPhase(str, Enum):
    WAIT = "wait"
    LOAD = "load"
    MOVE = "move"
    DROP = "drop"
    FIGHT = "fight"
    DONE = "done"


@dataclass
class DropRuntime:
    phase: DropPhase = DropPhase.WAIT
    medivac_tag: Optional[int] = None
    staging: Optional[Point2] = None
    target: Optional[Point2] = None
    next_loop: int = 0  # throttle simples pra não spammar command


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
        # game_loop é bem mais estável que "iteration" do seu log
        st = getattr(self.bot, "state", None)
        gl = getattr(st, "game_loop", None)
        if gl is not None:
            return int(gl)
        # fallback
        it = getattr(self.ctx, "iteration", None)
        return int(it) if it is not None else 0

    def _enemy_main(self) -> Optional[Point2]:
        locs = getattr(self.bot, "enemy_start_locations", None)
        if not locs:
            return None
        return locs[0]

    def _my_start(self) -> Optional[Point2]:
        return getattr(self.bot, "start_location", None)

    def _nearest_expansion_to(self, anchor: Point2) -> Optional[Point2]:
        exps = getattr(self.bot, "expansion_locations_list", None)
        if not exps:
            return None
        exps = list(exps)
        exps.sort(key=lambda p: p.distance_to(anchor))
        # [0] tende a ser a main; pega a segunda como “natural”
        return exps[1] if len(exps) > 1 else exps[0]

    def _point_by_key(self, key: str) -> Optional[Point2]:
        enemy_main = self._enemy_main()
        my_main = self._my_start()
        if key == "ENEMY_MAIN":
            return enemy_main
        if key == "MY_MAIN":
            return my_main
        if key == "ENEMY_NATURAL":
            return self._nearest_expansion_to(enemy_main) if enemy_main else None
        if key == "MY_NATURAL":
            return self._nearest_expansion_to(my_main) if my_main else None
        return None

    def _resolve_points(self, drop_cfg) -> tuple[Optional[Point2], Optional[Point2]]:
        enemy_main = self._enemy_main()
        my_main = self._my_start()
        if enemy_main is None or my_main is None:
            return None, None

        staging_key = getattr(drop_cfg, "staging", None) or "ENEMY_NATURAL"
        target_key = getattr(drop_cfg, "target", None) or "ENEMY_MAIN"

        staging_anchor = self._point_by_key(staging_key)
        target = self._point_by_key(target_key)

        if staging_anchor is None or target is None:
            return None, None

        # staging final: “um pouco antes” do staging_anchor, indo em direção ao meu main
        dist = getattr(drop_cfg, "staging_dist", None)
        dist = float(dist) if dist is not None else 18.0
        staging = staging_anchor.towards(my_main, dist)

        return staging, target
    def _emit(self, event: str, payload: dict):
        if self.log:
            self.log.emit(event, payload, meta={"iter": int(getattr(self.ctx, "iteration", 0))})



    async def _do(self, cmd) -> bool:
        """
        Compatível com:
        - python-sc2: bot.do(cmd) é coroutine
        - forks:      bot.do(cmd) é sync e retorna bool
        """
        fn = getattr(self.bot, "do", None)
        if fn is None:
            return False

        res = fn(cmd)
        if inspect.isawaitable(res):
            await res
            return True

        # se for bool, devolve ele; se for None, assume ok
        if isinstance(res, bool):
            return res
        return True
    def _medivac(self):
        meds = self.bot.units(U.MEDIVAC) if hasattr(self.bot, "units") else None
        if not meds:
            return None
        # preferir o tag fixado
        if self.rt.medivac_tag is not None:
            m = meds.find_by_tag(self.rt.medivac_tag)
            if m:
                return m
        # senão pega o primeiro pronto
        ready = meds.ready if hasattr(meds, "ready") else meds
        if ready:
            m = ready.first
            self.rt.medivac_tag = int(m.tag)
            return m
        return None

    # ----------------------------
    # main
    # ----------------------------
    async def step(self, budget: TickBudget, cfg: dict) -> bool:
        drop_cfg = cfg["drop"]
        if not drop_cfg.enabled:
            return False

        # throttle: evita repetir command todo loop
        loop = self._loop()
        if loop < self.rt.next_loop:
            return False

        if budget.remaining <= 0:
            return False

        # resolve staging/target uma vez
        if self.rt.staging is None or self.rt.target is None:
            staging, target = self._resolve_points(drop_cfg)
            self.rt.staging, self.rt.target = staging, target
            if staging is None or target is None:
                self._emit("drop_wait", {"reason": "no_points"})
                self.rt.next_loop = loop + 8
                return False

        # tunables (com fallback pro seu schema)
        min_marines = int(getattr(drop_cfg, "min_marines", 8))
        load_count = int(getattr(drop_cfg, "load_count", min_marines))
        move_eps = float(getattr(drop_cfg, "move_eps", 3.0))

        # units
        med = self._medivac()
        marines = self.bot.units(U.MARINE) if hasattr(self.bot, "units") else None
        marines_ready = marines.ready if marines and hasattr(marines, "ready") else marines

        if med is None:
            self._emit("drop_wait", {"reason": "no_medivac"})
            self.rt.next_loop = loop + 12
            return False

        if not marines_ready or marines_ready.amount < min_marines:
            self._emit("drop_wait", {"reason": "not_enough_marines", "have": int(marines_ready.amount if marines_ready else 0)})
            self.rt.next_loop = loop + 12
            return False

        # ----------------------------
        # STATE MACHINE
        # ----------------------------
        if self.rt.phase == DropPhase.WAIT:
            self._emit("drop_armed", {"phase": "wait", "min_marines": min_marines, "load_count": load_count})
            self.rt.phase = DropPhase.LOAD
            self.rt.next_loop = loop + 1
            return False

        if self.rt.phase == DropPhase.LOAD:
            # carrega os marines mais próximos do medivac
            # (não tenta ser perfeito agora; objetivo é funcionar)
            candidates = list(marines_ready)
            candidates.sort(key=lambda m: m.distance_to(med))
            to_load = candidates[:load_count]

            issued = 0
            for m in to_load:
                if budget.remaining <= 0:
                    break
                # LOAD no marine
                ok = await self._do(med(A.LOAD, m))
                if ok:
                    budget.remaining -= 1
                    issued += 1
                    break  # 1 cmd por tick pra não spammar

            # condição de avanço: medivac com cargo suficiente OU sem mais o que carregar
            cargo_used = int(getattr(med, "cargo_used", 0))
            if cargo_used >= load_count:
                self._emit("drop_loaded", {"cargo_used": cargo_used})
                self.rt.phase = DropPhase.MOVE
            else:
                self._emit("drop_loading", {"cargo_used": cargo_used, "target": load_count})

            self.rt.next_loop = loop + 4
            return issued > 0

        if self.rt.phase == DropPhase.MOVE:
            # move para staging
            if med.distance_to(self.rt.staging) <= move_eps:
                self._emit("drop_at_staging", {"pos": [float(med.position.x), float(med.position.y)]})
                self.rt.phase = DropPhase.DROP
                self.rt.next_loop = loop + 1
                return False

            ok = await self._do(med.move(self.rt.staging))
            if ok:
                budget.remaining -= 1
                self._emit("drop_move", {"to": [float(self.rt.staging.x), float(self.rt.staging.y)]})
                self.rt.next_loop = loop + 10
                return True

            self.rt.next_loop = loop + 10
            return False

        if self.rt.phase == DropPhase.DROP:
            # chega no alvo (target) e unload
            if med.distance_to(self.rt.target) > move_eps * 2:
                ok = await self._do(med.move(self.rt.target))
                if ok:
                    budget.remaining -= 1
                    self._emit("drop_approach", {"to": [float(self.rt.target.x), float(self.rt.target.y)]})
                    self.rt.next_loop = loop + 10
                    return True
                self.rt.next_loop = loop + 10
                return False

            ok = await self._do(med(A.UNLOADALLAT, self.rt.target))
            if ok:
                budget.remaining -= 1
                self._emit("drop_unload", {"at": [float(self.rt.target.x), float(self.rt.target.y)]})
                self.rt.phase = DropPhase.FIGHT
                self.rt.next_loop = loop + 8
                return True

            self.rt.next_loop = loop + 8
            return False

        if self.rt.phase == DropPhase.FIGHT:
            # manda marines atacar enemy main (ou target)
            ground = self.bot.units(U.MARINE) if hasattr(self.bot, "units") else None
            if ground and ground.amount > 0:
                # opcional: stim (só se existir a ability e você pesquisou)
                # Se não pesquisou, o command falha silencioso ou retorna erro; sem stress.
                for m in ground:
                    if budget.remaining <= 0:
                        break
                    if m.distance_to(self.rt.target) < 15 and getattr(m, "is_idle", True):
                        await self._do(m.attack(self.rt.target))
                        budget.remaining -= 1
                        self._emit("drop_attack", {"target": [float(self.rt.target.x), float(self.rt.target.y)]})
                        break

            self.rt.phase = DropPhase.DONE
            self.rt.next_loop = loop + 30
            return True

        if self.rt.phase == DropPhase.DONE:
            # por enquanto: one-shot
            return False

        return False
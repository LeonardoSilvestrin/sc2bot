#bot/strategy/plan_executor.py
from __future__ import annotations

from typing import Any, Dict, Optional

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId as Up
from sc2.position import Point2

from .schema import StrategyConfig


def _as_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _as_bool(x: Any, default: bool = False) -> bool:
    try:
        return bool(x)
    except Exception:
        return default


def parse_u(name: str) -> U:
    try:
        return getattr(U, name)
    except AttributeError as e:
        raise ValueError(f"UnitTypeId inválido no JSON: {name}") from e


def parse_up(name: str) -> Up:
    try:
        return getattr(Up, name)
    except AttributeError as e:
        raise ValueError(f"UpgradeId inválido no JSON: {name}") from e


_TEMPORARY_FAIL_REASONS: set[str] = {
    "cant_afford",
    "no_supply",
    "no_placement",
    "all_busy",
    "no_idle_parent",
    "do_failed",

    # NOVO: não mate o plan por isso
    "no_geyser_candidates",
    "all_geysers_occupied",
    "no_townhall",
    "no_workers",
}
_ALLOWED_NEAR_POINTS = {"MY_MAIN", "MY_NATURAL"}


class PlanExecutor:
    def __init__(self, bot: Any, builder: Any, strategy: StrategyConfig, *, ctx: Any, logger: Any | None = None):
        self.bot = bot
        self.builder = builder
        self.strategy = strategy
        self.ctx = ctx
        self.log = logger
        self._done_steps: set[str] = set()

        # opener runtime
        self._opener_done: bool = False
        self._opener_force_wall_active: bool = bool(getattr(self.strategy.opener, "force_wall", True))
        self._opener_no_place_streak: int = 0

        if self.log:
            self.log.emit(
                "strategy_loaded",
                {
                    "name": self.strategy.name,
                    "build_steps": int(len(self.strategy.build)),
                    "production_rules": int(len(self.strategy.production_rules)),
                    "opener": {
                        "enabled": bool(getattr(self.strategy.opener, "enabled", True)),
                        "force_wall": bool(getattr(self.strategy.opener, "force_wall", True)),
                        "depots": int(getattr(self.strategy.opener, "depots", 2)),
                        "barracks": int(getattr(self.strategy.opener, "barracks", 1)),
                    },
                },
                meta={"iter": int(getattr(self.ctx, "iteration", 0))},
            )

    async def step(self) -> None:
        # (0) opener obrigatório antes do plano
        if await self._run_opener_one_action():
            return

        # (1) build plan
        if await self._run_build_plan_one_step():
            return

        # (2) production rules
        await self._run_production_rules_one_action()

    # -----------------------
    # opener (MAIN wall)
    # -----------------------
    async def _run_opener_one_action(self) -> bool:
        opener = getattr(self.strategy, "opener", None)
        if opener is None or not bool(getattr(opener, "enabled", True)):
            self._opener_done = True
            return False

        if self._opener_done:
            return False

        depots_need = int(getattr(opener, "depots", 2))
        rax_need = int(getattr(opener, "barracks", 1))

        if depots_need <= 0 and rax_need <= 0:
            self._opener_done = True
            return False

        depots_total = int(self.builder.total(U.SUPPLYDEPOT))
        rax_total = int(self.builder.total(U.BARRACKS))

        if depots_total >= depots_need and rax_total >= rax_need:
            self._opener_done = True
            if self.log:
                self.log.emit(
                    "opener_complete",
                    {"depots_total": depots_total, "barracks_total": rax_total},
                    meta={"iter": int(self.ctx.iteration)},
                )
            return False

        # ordem fixa: depots -> barracks
        want = None
        if depots_total < depots_need:
            want = U.SUPPLYDEPOT
        elif rax_total < rax_need:
            want = U.BARRACKS

        if want is None:
            self._opener_done = True
            return False

        wall_pref = "MAIN" if self._opener_force_wall_active else None

        did = await self.builder.try_build(want, near=None, wall_pref=wall_pref)
        last = getattr(self.builder, "last", None)
        last_reason = str(getattr(last, "reason", "") or "")

        # se não conseguiu placement na wall repetidas vezes, faz fallback automático
        if not did and wall_pref is not None and last_reason == "no_placement":
            self._opener_no_place_streak += 1
            if self._opener_no_place_streak >= 8:
                self._opener_force_wall_active = False
                if self.log:
                    self.log.emit(
                        "opener_force_wall_disabled",
                        {"reason": "no_placement_streak", "streak": int(self._opener_no_place_streak)},
                        meta={"iter": int(self.ctx.iteration)},
                    )
        elif did:
            self._opener_no_place_streak = 0

        if self.log:
            self.log.emit(
                "opener_step",
                {
                    "want": want.name,
                    "did": bool(did),
                    "depots_total": depots_total,
                    "barracks_total": rax_total,
                    "force_wall_active": bool(self._opener_force_wall_active),
                    "last_reason": last_reason,
                },
                meta={"iter": int(self.ctx.iteration)},
            )

        return bool(did)

    # -----------------------
    # map-point helpers (near)
    # -----------------------
    def _my_start(self) -> Optional[Point2]:
        return getattr(self.bot, "start_location", None)

# --- PLAN_EXECUTOR: substituir _my_natural por esta versão ---

    def _my_natural(self) -> Optional[Point2]:
        loc = getattr(self.bot, "locations", None)
        if loc is not None:
            nat = loc.my_natural_exp()
            if nat is not None:
                return nat

        nat = getattr(self.bot, "cached_natural_expansion", None)
        if nat is not None:
            return nat

        exps = getattr(self.bot, "expansion_locations_list", None)
        my_main = self._my_start()
        if my_main is None or not exps:
            return None

        exps = list(exps)
        main_exp = min(exps, key=lambda p: p.distance_to(my_main))
        candidates = [p for p in exps if p.distance_to(main_exp) > 3.0]
        if not candidates:
            return None
        return min(candidates, key=lambda p: p.distance_to(main_exp))
    def _resolve_near(self, near_key: str | None) -> Optional[Point2]:
        if near_key is None:
            return None
        key = str(near_key).strip().upper()
        if key not in _ALLOWED_NEAR_POINTS:
            raise ValueError(f"near inválido: {key} (allowed={sorted(_ALLOWED_NEAR_POINTS)})")
        if key == "MY_MAIN":
            return self._my_start()
        if key == "MY_NATURAL":
            return self._my_natural()
        return None

    # -----------------------
    # main loop (build/production)
    # -----------------------
    async def _run_build_plan_one_step(self) -> bool:
        for step in self.strategy.build:
            name = str(step.get("name") or step.get("id") or "").strip() or f"_unnamed_{id(step)}"
            if name in self._done_steps:
                continue

            requires = step.get("requires") or {}
            when = step.get("when") or {}
            action = step.get("do") or {}

            if not self._check_conditions(requires):
                continue
            if not self._check_conditions(when):
                continue

            self._emit("plan_step_ready", {"name": name, "requires": requires, "when": when, "do": action})

            did = await self._execute_action(action)
            if did:
                self._done_steps.add(name)
                self._emit("plan_step_done", {"name": name, "do": action})
                return True

            last = getattr(self.builder, "last", None)
            last_reason = str(getattr(last, "reason", "") or "")
            last_details = getattr(last, "details", None)

            self._emit(
                "plan_step_blocked",
                {"name": name, "do": action, "last_reason": last_reason, "last_details": last_details},
            )

            if last_reason in _TEMPORARY_FAIL_REASONS:
                continue

            return False

        return False

    async def _run_production_rules_one_action(self) -> bool:
        for rule in self.strategy.production_rules:
            requires = rule.get("requires") or {}
            when = rule.get("when") or {}
            action = rule.get("do") or {}

            if not self._check_conditions(requires):
                continue
            if not self._check_conditions(when):
                continue

            self._emit("prod_rule_ready", {"name": rule.get("name", ""), "do": action})

            did = await self._execute_action(action)
            if did:
                self._emit("prod_rule_done", {"name": rule.get("name", ""), "do": action})
                return True

        return False

    def _check_conditions(self, cond: Dict[str, Any]) -> bool:
        if not cond:
            return True

        bot = self.bot

        if "minerals_gte" in cond and bot.minerals < _as_int(cond["minerals_gte"], 0):
            return False
        if "gas_gte" in cond and bot.vespene < _as_int(cond["gas_gte"], 0):
            return False

        if "supply_left_lte" in cond and bot.supply_left > _as_int(cond["supply_left_lte"], 0):
            return False
        if "supply_left_gte" in cond and bot.supply_left < _as_int(cond["supply_left_gte"], 0):
            return False

        if "supply_used_gte" in cond and bot.supply_used < _as_int(cond["supply_used_gte"], 0):
            return False
        if "supply_used_lte" in cond and bot.supply_used > _as_int(cond["supply_used_lte"], 0):
            return False

        if "supply_cap_gte" in cond and bot.supply_cap < _as_int(cond["supply_cap_gte"], 0):
            return False
        if "supply_cap_lte" in cond and bot.supply_cap > _as_int(cond["supply_cap_lte"], 0):
            return False

        if "have_gte" in cond and not self._check_unit_thresholds(cond["have_gte"], op="gte", mode="total"):
            return False
        if "have_lte" in cond and not self._check_unit_thresholds(cond["have_lte"], op="lte", mode="total"):
            return False
        if "ready_gte" in cond and not self._check_unit_thresholds(cond["ready_gte"], op="gte", mode="ready"):
            return False
        if "unit_gte" in cond and not self._check_unit_thresholds(cond["unit_gte"], op="gte", mode="total"):
            return False
        if "unit_lte" in cond and not self._check_unit_thresholds(cond["unit_lte"], op="lte", mode="total"):
            return False

        if "upgrade_done" in cond:
            ups = cond["upgrade_done"]
            if isinstance(ups, str):
                ups = [ups]
            if not isinstance(ups, list):
                raise TypeError("upgrade_done must be string or list of strings")
            for u in ups:
                up = parse_up(str(u))
                if not self.builder.has_upgrade(up):
                    return False

        if "upgrade_missing" in cond:
            ups = cond["upgrade_missing"]
            if isinstance(ups, str):
                ups = [ups]
            if not isinstance(ups, list):
                raise TypeError("upgrade_missing must be string or list of strings")
            for u in ups:
                up = parse_up(str(u))
                if self.builder.has_upgrade(up):
                    return False
                if self.builder.pending_upgrade(up) > 0:
                    return False

        return True

    def _check_unit_thresholds(self, table: Dict[str, Any], *, op: str, mode: str) -> bool:
        for k, v in table.items():
            ut = parse_u(str(k))
            thr = _as_int(v, 0)
            val = self.builder.ready(ut) if mode == "ready" else self.builder.total(ut)

            if op == "gte":
                if val < thr:
                    return False
            else:
                if val > thr:
                    return False
        return True

    async def _execute_action(self, action: Dict[str, Any]) -> bool:
        if not action:
            return False

        if "build" in action:
            ut = parse_u(str(action["build"]))

            limit = action.get("limit")
            if limit is not None and self.builder.total(ut) >= _as_int(limit, 0):
                return False
            if self.builder.pending(ut) > 0:
                return False

            near_key = action.get("near", None)
            near_pt = self._resolve_near(near_key) if near_key is not None else None
            return await self.builder.try_build(ut, near=near_pt)

        if "build_addon" in action:
            addon = str(action["build_addon"])
            on_name = str(action.get("on") or "").strip()
            if not on_name:
                raise ValueError("Action build_addon exige campo 'on' (ex: 'BARRACKS').")
            on_ut = parse_u(on_name)

            limit = action.get("limit")
            if limit is not None:
                addon_upper = addon.strip().upper()
                infer = None
                if on_ut == U.BARRACKS and addon_upper == "TECHLAB":
                    infer = U.BARRACKSTECHLAB
                elif on_ut == U.BARRACKS and addon_upper == "REACTOR":
                    infer = U.BARRACKSREACTOR
                elif on_ut == U.STARPORT and addon_upper == "REACTOR":
                    infer = U.STARPORTREACTOR
                elif on_ut == U.STARPORT and addon_upper == "TECHLAB":
                    infer = U.STARPORTTECHLAB
                elif on_ut == U.FACTORY and addon_upper == "TECHLAB":
                    infer = U.FACTORYTECHLAB
                elif on_ut == U.FACTORY and addon_upper == "REACTOR":
                    infer = U.FACTORYREACTOR

                if infer is not None and self.builder.total(infer) >= _as_int(limit, 0):
                    return False

            return await self.builder.try_addon(on=on_ut, addon=addon)

        if "research" in action:
            up = parse_up(str(action["research"]))
            return await self.builder.try_research(up)

        if "train" in action:
            ut = parse_u(str(action["train"]))
            from_name = str(action.get("from") or "").strip()
            if not from_name:
                raise ValueError("Action train exige campo 'from' (ex: 'BARRACKS').")
            ft = parse_u(from_name)

            cap = action.get("cap")
            if cap is not None and self.builder.total(ut) >= _as_int(cap, 0):
                return False

            return await self.builder.try_train(ut, from_type=ft)

        return False

    def _emit(self, event: str, payload: dict) -> None:
        if not self.log:
            return
        self.log.emit(event, payload, meta={"strategy": self.strategy.name, "iter": int(self.ctx.iteration)})
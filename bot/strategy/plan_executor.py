#bot/strategy/plan_executor.py
from __future__ import annotations

from typing import Any, Dict, Optional, List

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

        if self.log:
            self.log.emit(
                "strategy_loaded",
                {
                    "name": self.strategy.name,
                    "build_steps": int(len(self.strategy.build)),
                    "production_rules": int(len(self.strategy.production_rules)),
                },
                meta={"iter": int(getattr(self.ctx, "iteration", 0))},
            )

    async def step(self) -> None:
        if await self._run_build_plan_one_step():
            return
        await self._run_production_rules_one_action()

    # -----------------------
    # map-point helpers (near)
    # -----------------------
    def _my_start(self) -> Optional[Point2]:
        return getattr(self.bot, "start_location", None)

    def _expansions(self) -> List[Point2]:
        exps = getattr(self.bot, "expansion_locations_list", None)
        return list(exps) if exps else []

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
    # main loop
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

        # ---- normal build (structures/refinery/etc) ----
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

        # ---- addons ----
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

        # ---- research ----
        if "research" in action:
            up = parse_up(str(action["research"]))
            return await self.builder.try_research(up)

        # ---- train ----
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
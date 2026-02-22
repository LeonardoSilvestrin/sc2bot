# plan_executor.py
from __future__ import annotations

from typing import Any, Dict

from sc2.ids.unit_typeid import UnitTypeId as U

from .schema import StrategyConfig


def _as_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def parse_u(name: str) -> U:
    try:
        return getattr(U, name)
    except AttributeError as e:
        raise ValueError(f"UnitTypeId inválido no JSON: {name}") from e


class PlanExecutor:
    """
    Executa:
      - StrategyConfig.build: one-shot, em ordem
      - StrategyConfig.production_rules: regras repetíveis

    Política:
      - build: no máximo 1 step por tick
      - production_rules: no máximo 1 ação por tick
    """

    def __init__(self, bot: Any, builder: Any, strategy: StrategyConfig, *, ctx: Any, logger: Any | None = None):
        self.bot = bot
        self.builder = builder
        self.strategy = strategy
        self.ctx = ctx
        self.log = logger
        self._done_steps: set[str] = set()

        # loga o que veio do loader: isso denuncia build vazio na hora
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
        # 1) build plan (one-shot)
        if await self._run_build_plan_one_step():
            return

        # 2) produção contínua
        await self._run_production_rules_one_action()

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

            self._emit(
                "plan_step_blocked",
                {
                    "name": name,
                    "do": action,
                    "last_reason": getattr(getattr(self.builder, "last", None), "reason", ""),
                    "last_details": getattr(getattr(self.builder, "last", None), "details", None),
                },
            )
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

            return await self.builder.try_build(ut)

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
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

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
    Interpreta StrategyConfig.build (one-shot steps em ordem)
    e StrategyConfig.production_rules (regras repetíveis).
    """

    def __init__(self, bot, builder, strategy: StrategyConfig, logger=None):
        self.bot = bot
        self.builder = builder
        self.strategy = strategy
        self.log = logger
        self._done_steps: set[str] = set()

    async def step(self):
        # 0) economia base: distribui workers + SCV target via knobs
        await self.builder.economy.step()
        await self.builder.economy.train_scv(self.strategy.economy.scv_target)

        # 1) anti-supplyblock “genérico” via knobs (isso NÃO é build order; é safety)
        await self._auto_supply()

        # 2) build plan (executa no máximo 1 step por tick)
        did = await self._run_build_plan_one_step()
        if did:
            return

        # 3) produção contínua (executa no máximo 1 ação por tick)
        await self._run_production_rules_one_action()

    # ----------------------------
    # safety (não é estratégia)
    # ----------------------------
    async def _auto_supply(self) -> bool:
        # regra simples: se supply baixo, tenta depot.
        # Se você quiser 100% “tudo no JSON”, pode remover e colocar um step repetível de supply.
        bot = self.bot
        trigger = self.strategy.economy.depot_trigger_supply_left

        if bot.supply_left > trigger:
            return False

        # evita spam
        if self.builder.pending(U.SUPPLYDEPOT) > 0:
            return False

        # se já tem barracks e ainda assim supply baixo, também vale
        return await self.builder.try_build(U.SUPPLYDEPOT)

    # ----------------------------
    # plan execution
    # ----------------------------
    async def _run_build_plan_one_step(self) -> bool:
        for step in self.strategy.build:
            name = str(step.get("name") or step.get("id") or "")
            # se não tem name, gera um determinístico pelo índice (ruim), então exija name
            if not name:
                # fallback: executa, mas não marca; melhor você colocar "name" no JSON
                name = f"_unnamed_{id(step)}"

            if name in self._done_steps:
                continue

            requires = step.get("requires") or {}
            when = step.get("when") or {}

            if not self._check_conditions(requires):
                continue
            if not self._check_conditions(when):
                continue

            action = step.get("do") or {}
            if self.log:
                self.log.emit("plan_step_ready", {"name": name, "requires": requires, "when": when, "do": action},
                            meta={"iteration": int(self.bot.state.game_loop)} if hasattr(self.bot, "state") else None)

            did = await self._execute_action(action)

            if did and self.log:
                self.log.emit("plan_step_done", {"name": name, "do": action}, meta={"strategy": self.strategy.name})

            # “build plan” é one-shot: marca como feito se disparou algo
            if did:
                self._done_steps.add(name)
                return True

        return False

    async def _run_production_rules_one_action(self) -> bool:
        for rule in self.strategy.production_rules:
            requires = rule.get("requires") or {}
            when = rule.get("when") or {}
            if not self._check_conditions(requires):
                continue
            if not self._check_conditions(when):
                continue

            action = rule.get("do") or {}
            if self.log:
                self.log.emit("action_attempt", {"kind": "production", "name": rule.get("name",""), "do": action},
                            meta={"strategy": self.strategy.name, "iter": int(self.bot.state.iteration)})

            did = await self._execute_action(action)

            if did and self.log:
                self.log.emit("action_issued", {"kind": "production", "name": rule.get("name",""), "do": action},
                            meta={"strategy": self.strategy.name, "iter": int(self.bot.state.iteration)})

            if did:
                return True
            # produção: roda repetível, mas limita 1 ação por tick pra não spammar
            if did:
                return True
        return False

    # ----------------------------
    # conditions
    # ----------------------------
    def _check_conditions(self, cond: Dict[str, Any]) -> bool:
        """
        cond supports:
          - minerals_gte
          - gas_gte
          - supply_left_lte
          - supply_left_gte
          - have_gte: { "BARRACKS": 1, ... }   # usa TOTAL (inclui pending)
          - have_lte: { ... }                 # usa TOTAL
          - ready_gte: { ... }                # usa READY
          - unit_lte: { ... }                 # vivos+pending (TOTAL)
          - unit_gte: { ... }
        """
        if not cond:
            return True

        bot = self.bot

        # simples
        if "minerals_gte" in cond and bot.minerals < _as_int(cond["minerals_gte"], 0):
            return False
        if "gas_gte" in cond and bot.vespene < _as_int(cond["gas_gte"], 0):
            return False
        if "supply_left_lte" in cond and bot.supply_left > _as_int(cond["supply_left_lte"], 0):
            return False
        if "supply_left_gte" in cond and bot.supply_left < _as_int(cond["supply_left_gte"], 0):
            return False

        # dict-based
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
        """
        table ex: {"BARRACKS": 1}
        mode: "total" (have+pending) | "ready"
        op: "gte" | "lte"
        """
        for k, v in table.items():
            ut = parse_u(str(k))
            thr = _as_int(v, 0)

            if mode == "ready":
                val = self.builder.ready(ut)
            else:
                val = self.builder.total(ut)

            if op == "gte":
                if val < thr:
                    return False
            else:  # lte
                if val > thr:
                    return False

        return True

    # ----------------------------
    # actions
    # ----------------------------
    async def _execute_action(self, action: Dict[str, Any]) -> bool:
        """
        action supports:
          - {"build": "SUPPLYDEPOT"}
          - {"train": "MARINE", "from": "BARRACKS", "cap": 24}
        """
        if not action:
            return False

        # BUILD
        if "build" in action:
            ut = parse_u(str(action["build"]))

            # idempotência opcional: se cap/limit for definido no step, respeita
            limit = action.get("limit")
            if limit is not None and self.builder.total(ut) >= _as_int(limit, 0):
                return False

            # anti-spam: se já tem pending desse prédio, costuma ser suficiente
            if self.builder.pending(ut) > 0:
                return False

            return await self.builder.try_build(ut)

        # TRAIN
        if "train" in action:
            ut = parse_u(str(action["train"]))
            from_name = str(action.get("from") or "")
            if not from_name:
                raise ValueError("Action train exige campo 'from' (ex: 'BARRACKS').")
            ft = parse_u(from_name)

            cap = action.get("cap")
            if cap is not None:
                if self.builder.total(ut) >= _as_int(cap, 0):
                    return False

            return await self.builder.try_train(ut, from_type=ft)

        return False
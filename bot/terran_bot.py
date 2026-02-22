#bot/terran_bot.py
from __future__ import annotations

from sc2.bot_ai import BotAI

from bot.core.state import BotState
from bot.core.logger import JsonlLogger
from bot.core.unit_manager import UnitManager

from bot.engine.economy import Economy
from bot.engine.placement import Placement
from bot.engine.builder import Builder
from bot.engine.expansion_finder import compute_main_and_natural

from bot.strategy.loader import load_strategy
from bot.strategy.plan_executor import PlanExecutor

from bot.behaviors.macro import MacroBehavior
from bot.behaviors.drop import DropBehavior
from bot.behaviors.combat import CombatBehavior
from bot.behaviors.plan import PlanBehavior
from bot.behaviors.orchestrator import BehaviorOrchestrator


class TerranBot(BotAI):
    def __init__(self, strat_name: str = "default", debug: bool = True):
        super().__init__()
        self.debug = debug
        self.ctx = BotState()

        self.log = JsonlLogger(enabled=True)
        self.strategy = load_strategy(strat_name)
        self.log.emit("bot_init", {"strategy": self.strategy.name, "strat_name": str(strat_name)})

        # cache de expansões por pathing
        self.cached_main_expansion = None
        self.cached_natural_expansion = None
        self._exp_cache = {}
        self._next_exp_recalc_iter = 0

        self.econ = Economy(self, ctx=self.ctx, logger=self.log)

        # wall_main continua ON (para placement usar spots quando pedirmos wall_pref="MAIN")
        # wall_natural depende strategy.wall_natural
        self.place = Placement(
            self,
            ctx=self.ctx,
            logger=self.log,
            wall_main=True,
            wall_natural=bool(getattr(self.strategy, "wall_natural", False)),
            debug=debug,
        )

        self.builder = Builder(self, self.econ, self.place, self.ctx, logger=self.log)
        self.unitmgr = UnitManager(self, self.ctx, logger=self.log, debug=debug)

        self.macro = MacroBehavior(self, self.econ, self.builder, ctx=self.ctx, logger=self.log, debug=debug)

        # PlanExecutor agora contém o opener obrigatório (2 depots + 1 rax) com opção de override via JSON
        self.plan_exec = PlanExecutor(self, self.builder, self.strategy, ctx=self.ctx, logger=self.log)
        self.plan = PlanBehavior(self.plan_exec)

        self.combat = CombatBehavior(self, self.ctx, logger=self.log, debug=debug)

        self.drop_pairs: list[tuple[DropBehavior, dict]] = []
        for dc in getattr(self.strategy, "drops", []):
            drop_id = str(getattr(dc, "name", "") or "drop").strip() or "drop"
            beh = DropBehavior(self, self.ctx, self.unitmgr, drop_id=drop_id, logger=self.log, debug=debug)
            self.drop_pairs.append((beh, {"drop": dc}))

        self.orch = BehaviorOrchestrator()
        self._last_snapshot_iter = -999999

    def _active_pairs(self):
        # Ordem importa: macro antes/ depois do plan é discutível, mas aqui plan vem cedo.
        # O opener do plan é “build action” e vai competir com macro_supply — normal.
        pairs = [
            (self.plan, {"strategy": self.strategy}),
            (self.macro, {"econ": self.strategy.economy, "macro": self.strategy.behaviors.macro}),
        ]
        for beh, cfg in self.drop_pairs:
            pairs.append((beh, cfg))
        pairs.append((self.combat, {"combat": self.strategy.behaviors.combat}))
        return pairs

    def _compute_budget(self) -> int:
        drops = getattr(self.strategy, "drops", [])
        enabled_drops = sum(1 for d in drops if getattr(d, "enabled", False))
        # mantém a ideia original: 2 ações por tick se tiver 2 drops
        return 2 if enabled_drops >= 2 else 1

    async def _recalc_expansions_if_needed(self, iteration: int) -> None:
        if iteration < int(self._next_exp_recalc_iter):
            return

        exps = getattr(self, "expansion_locations_list", None)
        start = getattr(self, "start_location", None)
        if not exps or start is None:
            return

        main, nat = await compute_main_and_natural(self, expansions=list(exps), start=start, cache=self._exp_cache)
        self.cached_main_expansion = main
        self.cached_natural_expansion = nat

        self.log.emit(
            "expansion_pathing",
            {
                "main": [float(main.x), float(main.y)] if main else None,
                "natural": [float(nat.x), float(nat.y)] if nat else None,
            },
            meta={"iter": int(iteration)},
        )
        self._next_exp_recalc_iter = iteration + 110

    async def on_step(self, iteration: int):
        self.ctx.iteration = int(iteration)
        self.unitmgr.begin_tick(int(iteration))

        await self._recalc_expansions_if_needed(int(iteration))

        if iteration - self._last_snapshot_iter >= 22:
            self._last_snapshot_iter = iteration
            self.log.emit(
                "snapshot",
                {
                    "iteration": int(iteration),
                    "time": float(self.time),
                    "minerals": int(self.minerals),
                    "gas": int(self.vespene),
                    "supply_used": int(self.supply_used),
                    "supply_cap": int(self.supply_cap),
                    "supply_left": int(self.supply_left),
                    "workers": int(self.workers.amount),
                },
                meta={"strategy": self.strategy.name, "iter": int(self.ctx.iteration)},
            )

        self.orch.set_active(self._active_pairs())
        await self.orch.step(budget_actions=self._compute_budget())

    async def on_end(self, game_result):
        self.log.emit("game_end", {"result": str(game_result), "time": float(self.time)})
        self.log.close()
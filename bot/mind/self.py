# bot/mind/self.py
from __future__ import annotations

from dataclasses import dataclass

from sc2.data import Result

from bot.devlog import DevLogger
from bot.intel.threat_intel import Threat
from bot.intel.economy_intel import EconomyIntelConfig, derive_economy_intel
from bot.mind.attention import derive_attention
from bot.mind.awareness import Awareness
from bot.mind.body import UnitLeases  # Body
from bot.mind.ego import Ego, EgoConfig
from bot.tasks.base_task import TaskTick

from bot.tasks.defend_task import Defend
from bot.tasks.scout_task import Scout
from bot.tasks.macro_task import MacroBio2BaseTick, MacroOpeningTick

from bot.planners.defense_planner import DefensePlanner
from bot.planners.intel_planner import IntelPlanner
from bot.planners.macro_planner import MacroPlanner


@dataclass
class RuntimeApp:
    """
    Orquestrador único do bot.
    - Não toma decisão de plano/fase aqui.
    - Só chama derives (attention/intel) e roda o Ego.
    """

    log: DevLogger
    awareness: Awareness
    threat: Threat
    body: UnitLeases
    ego: Ego
    economy_cfg: EconomyIntelConfig
    debug: bool = True

    @classmethod
    def build(cls, *, log: DevLogger, debug: bool = True) -> "RuntimeApp":
        awareness = Awareness()
        threat = Threat(defend_radius=22.0, min_enemy=1)

        body = UnitLeases(default_ttl=8.0)

        ego = Ego(
            body=body,
            log=log,
            cfg=EgoConfig(
                one_commitment_per_domain=False,
                threat_block_start_at=70,
                threat_force_preempt_at=90,
                non_preemptible_grace_s=2.5,
                default_failure_cooldown_s=8.0,
            ),
        )

        # ---- Tasks (template instances)
        defend_task = Defend(log=log, log_every_iters=11)

        scout_task = Scout(
            body=body,
            awareness=awareness,
            log=log,
            trigger_time=25.0,
            log_every=6.0,
            see_radius=14.0,
        )

        opening_macro_task = MacroOpeningTick(
            log=log,
            log_every_iters=22,
            scv_cap=60,
        )

        macro_task = MacroBio2BaseTick(
            log=log,
            log_every_iters=22,
            scv_cap=60,
            target_bases=3,
            backoff_urgency=60,
        )

        # ---- Planners
        defense_planner = DefensePlanner(defend_task=defend_task)
        intel_planner = IntelPlanner(awareness=awareness, log=log, scout_task=scout_task)
        macro_planner = MacroPlanner(
            opening_task=opening_macro_task,
            macro_task=macro_task,
            backoff_urgency=60,
            opening_timeout_s=180.0,
        )

        ego.register_planners([defense_planner, intel_planner, macro_planner])

        return cls(
            log=log,
            awareness=awareness,
            threat=threat,
            body=body,
            ego=ego,
            economy_cfg=EconomyIntelConfig(),
            debug=bool(debug),
        )

    async def on_step(self, bot, *, iteration: int) -> None:
        now = float(getattr(bot, "time", 0.0))

        # 1) Perception / attention (snapshot factual)
        attention = derive_attention(bot, awareness=self.awareness, threat=self.threat)

        # 2) Economy intel (side-effect na Awareness; não sobrescreve attention)
        derive_economy_intel(bot, awareness=self.awareness, attention=attention, now=now, cfg=self.economy_cfg)

        # 3) Ego (decide + executa)
        tick = TaskTick(iteration=int(iteration), time=now)
        await self.ego.tick(bot, tick=tick, attention=attention, awareness=self.awareness)

    async def on_end(self, bot, game_result: Result) -> None:
        if self.log:
            self.log.emit("game_end", {"result": str(game_result)})
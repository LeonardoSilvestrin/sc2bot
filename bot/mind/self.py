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
                one_commitment_per_domain=True,
                threat_block_start_at=70,
                threat_force_preempt_at=90,
                non_preemptible_grace_s=2.5,
                default_failure_cooldown_s=8.0,
            ),
        )

        # ---- Tasks
        defend_task = Defend(log=log, log_every_iters=11)

        scout_task = Scout(
            body=body,             # FIX: kw compat com assinatura atual da task
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
        defense_planner = DefensePlanner(awareness=awareness, defend_task=defend_task)
        intel_planner = IntelPlanner(awareness=awareness, log=log, scout_task=scout_task)
        macro_planner = MacroPlanner(
            opening_task=opening_macro_task,
            macro_task=macro_task,
            backoff_urgency=60,
            opening_timeout_s=180.0,
        )

        ego.register_planners([defense_planner, intel_planner, macro_planner])

        economy_cfg = EconomyIntelConfig(macro_profile="BIO_2BASE", target_bases=3)

        return cls(
            log=log,
            awareness=awareness,
            threat=threat,
            body=body,
            ego=ego,
            economy_cfg=economy_cfg,
            debug=debug,
        )

    async def on_start(self, bot) -> None:
        map_name = bot.game_info.map_name
        enemy = bot.enemy_race.name
        fname = f"MyBot__{map_name}__vs__{enemy}__start.jsonl".replace(" ", "_")
        self.log.set_file(fname)

        self.log.emit("bot_init", {"strategy": "terran_builds.yml/Default"}, meta={"map": map_name})

        if self.debug:
            print(f"[on_start] devlog={self.log.log_dir}/{fname}")

    async def on_step(self, bot, *, iteration: int) -> None:
        now = float(getattr(bot, "time", 0.0))

        # 1) Perception / attention (snapshot factual)
        attention = derive_attention(bot, awareness=self.awareness, threat=self.threat)


        # 3) Ego tick (admission + execution + feedback)
        await self.ego.tick(
            bot,
            tick=TaskTick(iteration=iteration, time=now),
            attention=attention,
            awareness=self.awareness,
        )

        # 4) Snapshots (debug/telemetry)
        if iteration % 44 == 0:
            intel = self.awareness.intel_snapshot(now=now)
            mem_intel = self.awareness.mem.snapshot(now=now, prefix=("intel",), max_age=600.0)
            mem_plan = self.awareness.mem.snapshot(now=now, prefix=("plan",), max_age=None)
            mem_ops = self.awareness.mem.snapshot(now=now, prefix=("ops",), max_age=None)

            self.log.emit(
                "awareness_snapshot",
                {
                    "time": round(now, 2),
                    "attention": {
                        "opening_done": attention.macro.opening_done,
                        "threatened": attention.combat.threatened,
                        "urgency": attention.combat.defense_urgency,
                        "enemy_count_near_bases": attention.combat.enemy_count_near_bases,
                        "orbital_ready_to_scan": attention.intel.orbital_ready_to_scan,
                        "orbital_energy": round(attention.intel.orbital_energy, 1),
                    },
                    "plan": mem_plan,
                    "intel": intel,
                    "mem_intel": mem_intel,
                    "ops": mem_ops,
                    "events_tail": self.awareness.tail_events(6),
                    "body": self.body.snapshot(now=now) if hasattr(self.body, "snapshot") else {},
                },
            )

        if self.debug and iteration % 44 == 0:
            intel = self.awareness.intel_snapshot(now=now)
            plan = self.awareness.mem.snapshot(now=now, prefix=("plan",), max_age=None)
            plan_macro = plan.get("plan/macro")
            plan_phase = plan.get("plan/phase")

            try:
                su = int(getattr(bot, "supply_used", 0) or 0)
                sc = int(getattr(bot, "supply_cap", 0) or 0)
            except Exception:
                su, sc = 0, 0

            print(
                f"[tick] iter={iteration} t={now:.1f} "
                f"s={su}/{sc} "
                f"opening_done={attention.macro.opening_done} "
                f"threat={attention.combat.threatened} urg={attention.combat.defense_urgency} "
                f"plan={plan_macro}:{plan_phase} "
                f"intel(scv={intel['scv_dispatched']}/{intel['scv_arrived_main']}, scan={intel['scanned_enemy_main']})"
            )

    async def on_end(self, bot, *, game_result: Result) -> None:
        self.log.emit("game_end", {"result": str(game_result)})
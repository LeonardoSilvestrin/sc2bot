# bot/tasks/scout.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ares.consts import UnitRole
from sc2.unit import Unit

from bot.infra.unit_leases import UnitLeases
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.tasks.base import TaskStatus, TaskTick


@dataclass
class ScoutState:
    dispatched: bool = False
    arrived: bool = False
    scout_tag: Optional[int] = None
    last_seen_log_at: float = 0.0


class Scout:
    """
    INTEL task:
      - Dispara um SCV scout após trigger_time
      - Move até enemy main (Ares map wrapper)
      - Marca flags em Awareness
      - Loga estruturas vistas periodicamente
      - Usa UnitLeases para evitar disputa por unidade
    """

    task_id = "scout_worker_main"
    domain = "INTEL"
    commitment = 10
    status = TaskStatus.ACTIVE

    def __init__(
        self,
        *,
        leases: UnitLeases,
        awareness: Awareness,
        trigger_time: float = 25.0,
        log_every: float = 6.0,
        see_radius: float = 14.0,
        lease_ttl: float = 10.0,
        pause_at_urgency: int = 70,
        resume_below_urgency: int = 50,
    ):
        self.leases = leases
        self.awareness = awareness

        self.trigger_time = float(trigger_time)
        self.log_every = float(log_every)
        self.see_radius = float(see_radius)
        self.lease_ttl = float(lease_ttl)

        self.pause_at_urgency = int(pause_at_urgency)
        self.resume_below_urgency = int(resume_below_urgency)

        self.state = ScoutState()

    def is_done(self) -> bool:
        return self.status == TaskStatus.DONE

    def _get_scout(self, bot) -> Optional[Unit]:
        if self.state.scout_tag is None:
            return None
        return bot.units.find_by_tag(self.state.scout_tag)

    def evaluate(self, bot, attention: Attention) -> int:
        # Se já finalizou, não compete
        if self.is_done():
            return 0

        # Evita insistir quando defesa está apertada
        if attention.threatened and attention.defense_urgency >= self.pause_at_urgency:
            return 1

        # Se já despachou, score baixo (deixa outras coisas acontecerem)
        if self.state.dispatched:
            return 2

        # Ainda não despachou => interesse moderado
        return 20

    async def pause(self, bot, reason: str) -> None:
        if self.status != TaskStatus.PAUSED:
            self.status = TaskStatus.PAUSED
            bot.log.emit("scout_paused", {"reason": reason, "time": round(float(getattr(bot, "time", 0.0)), 2)})

    async def abort(self, bot, reason: str) -> None:
        tag = int(self.state.scout_tag) if self.state.scout_tag is not None else None

        # solta lease se existia
        self.leases.release_owner(task_id=self.task_id)

        self.status = TaskStatus.DONE
        bot.log.emit("scout_aborted", {"reason": reason, "time": round(float(bot.time), 2), "scout_tag": tag})

    async def step(self, bot, tick: TaskTick, attention: Attention) -> bool:
        if self.is_done():
            return False

        # pausa/resume automático
        if self.status == TaskStatus.PAUSED:
            if attention.defense_urgency < self.resume_below_urgency:
                self.status = TaskStatus.ACTIVE
                bot.log.emit("scout_resumed", {"time": round(float(bot.time), 2)})
            else:
                return False

        if attention.threatened and attention.defense_urgency >= self.pause_at_urgency:
            await self.pause(bot, reason=f"threat urgency={attention.defense_urgency}")
            return False

        target, source = bot.ares.map.enemy_main()
        if source != "ENEMY_START" and tick.iteration % 44 == 0:
            bot.log.emit("map_fallback", {"source": source, "time": round(float(bot.time), 2)})

        # 1) disparo (uma vez)
        if not self.state.dispatched:
            if float(bot.time) < self.trigger_time:
                return False

            worker: Unit = bot.ares.roles.request_worker_scout(target_position=target)

            now = float(bot.time)
            ok = self.leases.claim(
                task_id=self.task_id,
                unit_tag=int(worker.tag),
                role=UnitRole.BUILD_RUNNER_SCOUT,
                now=now,
                ttl=self.lease_ttl,
                force=False,
            )
            if not ok:
                # alguém já pegou a unidade; tenta de novo em ticks futuros
                return False

            worker.move(target)

            self.state.dispatched = True
            self.state.scout_tag = int(worker.tag)

            # awareness persistente
            self.awareness.intel.scv_dispatched = True
            self.awareness.intel.last_scv_dispatch_at = now

            bot.log.emit(
                "scout_dispatch",
                {
                    "iteration": tick.iteration,
                    "time": round(now, 2),
                    "scout_tag": int(worker.tag),
                    "target": [round(target.x, 1), round(target.y, 1)],
                    "trigger_time": self.trigger_time,
                    "map_source": source,
                },
            )
            return True

        # 2) pós-dispatch
        scout = self._get_scout(bot)
        if scout is None:
            await self.abort(bot, reason="scout_missing")
            return False

        # mantém lease viva
        self.leases.touch(task_id=self.task_id, unit_tag=int(scout.tag), now=float(bot.time), ttl=self.lease_ttl)

        # chegou no main?
        if (not self.state.arrived) and scout.distance_to(target) <= 8:
            self.state.arrived = True
            self.awareness.intel.scv_arrived_main = True

            bot.log.emit(
                "scout_arrived",
                {
                    "iteration": tick.iteration,
                    "time": round(float(bot.time), 2),
                    "scout_tag": int(scout.tag),
                    "pos": [round(scout.position.x, 1), round(scout.position.y, 1)],
                },
            )

        # log periódico do que viu
        if (float(bot.time) - float(self.state.last_seen_log_at)) >= self.log_every:
            self.state.last_seen_log_at = float(bot.time)

            seen = bot.enemy_structures.closer_than(self.see_radius, scout.position)
            bot.log.emit(
                "scout_seen_structures",
                {
                    "iteration": tick.iteration,
                    "time": round(float(bot.time), 2),
                    "scout_tag": int(scout.tag),
                    "scout_pos": [round(scout.position.x, 1), round(scout.position.y, 1)],
                    "count": int(seen.amount),
                    "types": [s.type_id.name for s in seen],
                },
            )

        # não emite comando todo tick (evita spam)
        return False
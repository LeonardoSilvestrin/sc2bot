# bot/tasks/scout.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sc2.position import Point2

from ares.consts import UnitRole

from bot.devlog import DevLogger
from bot.infra.unit_leases import UnitLeases
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.tasks.base import BaseTask, TaskTick


@dataclass
class Scout(BaseTask):
    leases: UnitLeases = None
    awareness: Awareness = None
    log: DevLogger | None = None

    trigger_time: float = 25.0
    log_every: float = 6.0
    see_radius: float = 14.0

    def __init__(
        self,
        *,
        leases: UnitLeases,
        awareness: Awareness,
        log: DevLogger | None = None,
        trigger_time: float = 25.0,
        log_every: float = 6.0,
        see_radius: float = 14.0,
    ):
        super().__init__(task_id="scout_scv", domain="INTEL")
        self.leases = leases
        self.awareness = awareness
        self.log = log
        self.trigger_time = float(trigger_time)
        self.log_every = float(log_every)
        self.see_radius = float(see_radius)

        self._scv_tag: Optional[int] = None
        self._target: Optional[Point2] = None
        self._last_log_t: float = 0.0

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> bool:
        now = float(tick.time)

        if now < self.trigger_time:
            self._paused("before_trigger_time")
            return False

        if self._scv_tag is None:
            if bot.workers.amount == 0:
                self._paused("no_worker_available")
                return False

            scv = bot.workers.random
            ok = self.leases.try_acquire(
                self.task_id,
                unit_tag=int(scv.tag),
                now=now,
                role=UnitRole.SCOUTING,
            )
            if not ok:
                self._paused("lease_denied")
                return False

            self._scv_tag = int(scv.tag)
            self.awareness.mark_scv_dispatched(now=now)

            try:
                self._target = bot.enemy_start_locations[0]
            except Exception:
                self._target = bot.game_info.map_center

            if self.log:
                self.log.emit("scout_started", {"t": round(now, 2), "scv_tag": self._scv_tag})
            self._active("scout_started")

        scv = bot.units.find_by_tag(self._scv_tag)
        if scv is None:
            self.leases.release_owner(task_id=self.task_id)
            self._done("unit_missing")
            self.awareness.emit("scout_lost", now=now)
            return False

        # keep lease alive
        self.leases.touch(task_id=self.task_id, unit_tag=self._scv_tag, now=now)

        if self._target:
            scv.move(self._target)

        if self._target and scv.position.distance_to(self._target) <= self.see_radius:
            if not self.awareness.intel_scv_arrived_main(now=now):
                self.awareness.mark_scv_arrived_main(now=now)
                if self.log:
                    self.log.emit("scout_arrived_main", {"t": round(now, 2)})

        if now - self._last_log_t >= self.log_every:
            self._last_log_t = now
            if self.log:
                self.log.emit(
                    "scout_status",
                    {"t": round(now, 2), "arrived": bool(self.awareness.intel_scv_arrived_main(now=now))},
                )

        self._active("scouting")
        return True
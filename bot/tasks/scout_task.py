# bot/tasks/scout_task.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.mind.body import UnitLeases
from bot.tasks.base_task import BaseTask, TaskTick, TaskResult


@dataclass
class Scout(BaseTask):
    # required deps first (avoid dataclass non-default-after-default errors)
    body: UnitLeases
    awareness: Awareness

    # config
    log: DevLogger | None = None
    trigger_time: float = 25.0
    log_every: float = 6.0
    see_radius: float = 14.0

    # internal state (not part of __init__)
    _scv_tag: Optional[int] = field(default=None, init=False)
    _target: Optional[Point2] = field(default=None, init=False)
    _last_log_t: float = field(default=0.0, init=False)

    def __init__(
        self,
        *,
        body: UnitLeases,
        awareness: Awareness,
        log: DevLogger | None = None,
        trigger_time: float = 25.0,
        log_every: float = 6.0,
        see_radius: float = 14.0,
    ):
        super().__init__(task_id="scout_enemy_main", domain="INTEL", commitment=2)
        self.body = body
        self.awareness = awareness
        self.log = log
        self.trigger_time = float(trigger_time)
        self.log_every = float(log_every)
        self.see_radius = float(see_radius)

        self._scv_tag = None
        self._target = None
        self._last_log_t = 0.0

    def evaluate(self, bot, attention: Attention) -> int:
        now = float(attention.time)

        # before trigger time: don't bother
        if now < float(self.trigger_time):
            return 0

        # already have intel: no need
        if self.awareness.intel_scv_arrived_main(now=now):
            return 0

        # opening can also be used as a mild incentive to scout early
        opening = bool(attention.macro.opening_done)
        return 55 if not opening else 35

    def _log_tick(self, bot, *, now: float, reason: str) -> None:
        if not self.log:
            return
        if now - float(self._last_log_t) < float(self.log_every):
            return
        self._last_log_t = float(now)
        self.log.emit(
            "scout_tick",
            {
                "t": round(float(now), 2),
                "reason": str(reason),
                "scv_tag": int(self._scv_tag or 0),
                "arrived": bool(self.awareness.intel_scv_arrived_main(now=now)),
                "dispatched": bool(self.awareness.intel_scv_dispatched(now=now)),
            },
        )

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        now = float(tick.time)

        if now < float(self.trigger_time):
            self._paused("too_early")
            return TaskResult.noop("too_early")

        if self.awareness.intel_scv_arrived_main(now=now):
            self._done("already_arrived")
            return TaskResult.done("already_arrived")

        # determine target once
        if self._target is None:
            try:
                target = bot.enemy_start_locations[0]
            except Exception:
                target = bot.game_info.map_center
            self._target = target

        # dispatch if needed
        if not self.awareness.intel_scv_dispatched(now=now) or self._scv_tag is None:
            try:
                worker = bot.workers.closest_to(bot.start_location)
            except Exception:
                worker = None

            if worker is None:
                self._paused("no_worker")
                return TaskResult.noop("no_worker")

            # claim worker
            ok = self.body.claim(
                task_id=self.task_id,
                unit_tag=int(worker.tag),
                role=bot.mediator.get_role(tag=worker.tag),
                now=now,
                ttl=10.0,
                force=False,
            )
            if not ok:
                self._paused("worker_leased")
                return TaskResult.noop("worker_leased")

            self._scv_tag = int(worker.tag)
            self.awareness.mark_scv_dispatched(now=now)
            self._active("dispatch")
            self._log_tick(bot, now=now, reason="dispatch")
            return TaskResult.running("dispatch")

        # move scv
        scv = bot.units.find_by_tag(self._scv_tag)
        if scv is None:
            self._paused("scv_lost")
            self._scv_tag = None
            return TaskResult.noop("scv_lost")

        # keep lease alive
        self.body.touch(task_id=self.task_id, unit_tag=int(scv.tag), now=now, ttl=10.0)

        if self._target is not None:
            if scv.distance_to(self._target) <= float(self.see_radius):
                self.awareness.mark_scv_arrived_main(now=now)
                self._done("arrived_main")
                self._log_tick(bot, now=now, reason="arrived_main")
                return TaskResult.done("arrived_main")

            scv.move(self._target)
            self._active("moving")
            self._log_tick(bot, now=now, reason="moving")
            return TaskResult.running("moving")

        self._paused("no_target")
        return TaskResult.noop("no_target")
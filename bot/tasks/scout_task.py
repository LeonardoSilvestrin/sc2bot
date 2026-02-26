# bot/tasks/scout_task.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.tasks.base_task import BaseTask, TaskTick, TaskResult


@dataclass
class Scout(BaseTask):
    """
    SCV scout to enemy main.

    Contract (new architecture):
      - Ego assigns units via leases and passes them through assigned_tags.
      - Task MUST NOT claim/touch leases directly.
      - Task MUST use assigned_tags as the only unit source.
    """
    awareness: Awareness
    log: DevLogger | None = None
    trigger_time: float = 25.0
    log_every: float = 6.0
    see_radius: float = 14.0

    _target: Optional[Point2] = field(default=None, init=False)
    _last_log_t: float = field(default=0.0, init=False)

    def __init__(
        self,
        *,
        awareness: Awareness,
        log: DevLogger | None = None,
        trigger_time: float = 25.0,
        log_every: float = 6.0,
        see_radius: float = 14.0,
    ):
        super().__init__(task_id="scout_enemy_main", domain="INTEL", commitment=2)
        self.awareness = awareness
        self.log = log
        self.trigger_time = float(trigger_time)
        self.log_every = float(log_every)
        self.see_radius = float(see_radius)

        self._target = None
        self._last_log_t = 0.0

    def evaluate(self, bot, attention: Attention) -> int:
        now = float(attention.time)

        if now < float(self.trigger_time):
            return 0

        if self.awareness.intel_scv_arrived_main(now=now):
            return 0

        opening = bool(attention.macro.opening_done)
        return 55 if not opening else 35

    def _log_tick(self, *, now: float, reason: str, scv_tag: int) -> None:
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
                "scv_tag": int(scv_tag),
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

        if not self.assigned_tags:
            # Strict: planner asked for SCV; Ego should have assigned it. If not, it's a wiring bug.
            return TaskResult.failed("no_assigned_scv", retry_after_s=2.0)

        scv_tag = int(self.assigned_tags[0])
        scv = bot.units.find_by_tag(scv_tag)
        if scv is None:
            self._paused("scv_lost")
            return TaskResult.noop("scv_lost")

        # determine target once (STRICT)
        if self._target is None:
            self._target = bot.enemy_start_locations[0]

        # mark dispatched once (for planner gating / audit)
        if not self.awareness.intel_scv_dispatched(now=now):
            self.awareness.mark_scv_dispatched(now=now)

        if scv.distance_to(self._target) <= float(self.see_radius):
            self.awareness.mark_scv_arrived_main(now=now)
            self._done("arrived_main")
            self._log_tick(now=now, reason="arrived_main", scv_tag=scv_tag)
            return TaskResult.done("arrived_main")

        scv.move(self._target)
        self._active("moving")
        self._log_tick(now=now, reason="moving", scv_tag=scv_tag)
        return TaskResult.running("moving")
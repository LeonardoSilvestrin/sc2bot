# bot/tasks/scout.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List

from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.mind.body import UnitLeases  # Body
from bot.tasks.base_task import BaseTask, TaskTick, TaskResult


def _mission_assigned_tags(awareness: Awareness, *, mission_id: str, now: float) -> List[int]:
    """
    MVP: lê assigned_tags do fallback via Awareness.mem.
    """
    tags = awareness.mem.get(K("ops", "mission", mission_id, "assigned_tags"), now=now, default=[])
    try:
        return [int(x) for x in (tags or [])]
    except Exception:
        return []


@dataclass
class Scout(BaseTask):
    body: UnitLeases = None
    awareness: Awareness = None
    log: DevLogger | None = None

    trigger_time: float = 25.0
    log_every: float = 6.0
    see_radius: float = 14.0

    # injetado pelo planner/ego
    mission_id: Optional[str] = None

    # estado interno mínimo
    _scv_tag: Optional[int] = None
    _target: Optional[Point2] = None
    _last_log_t: float = 0.0

    def __init__(
        self,
        *,
        body=None,
        awareness: Awareness,
        log: DevLogger | None = None,
        trigger_time: float = 25.0,
        log_every: float = 6.0,
        see_radius: float = 14.0,
    ):
        super().__init__(task_id="scout_scv", domain="INTEL")

        # compat: aceita body= ou leases=
        self.body = body
        if self.body is None:
            raise TypeError("Scout requires body= (or leases= for legacy wiring)")

        self.awareness = awareness
        self.log = log
        self.trigger_time = float(trigger_time)
        self.log_every = float(log_every)
        self.see_radius = float(see_radius)

        self.mission_id = None
        self._scv_tag = None
        self._target = None
        self._last_log_t = 0.0

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        now = float(tick.time)

        if now < self.trigger_time:
            self._paused("before_trigger_time")
            return TaskResult.noop("before_trigger_time")

        if not self.mission_id:
            self._paused("no_mission_id")
            self.awareness.emit("scout_failed", now=now, data={"reason": "no_mission_id"})
            return TaskResult.failed("no_mission_id", retry_after_s=6.0)

        if self._scv_tag is None:
            tags = _mission_assigned_tags(self.awareness, mission_id=self.mission_id, now=now)
            if not tags:
                self._paused("no_assigned_unit")
                self.awareness.emit(
                    "scout_failed",
                    now=now,
                    data={"reason": "no_assigned_unit", "mission_id": self.mission_id},
                )
                return TaskResult.failed("no_assigned_unit", retry_after_s=8.0)

            self._scv_tag = int(tags[0])

            if not self.awareness.intel_scv_dispatched(now=now):
                self.awareness.mark_scv_dispatched(now=now)

            try:
                self._target = bot.enemy_start_locations[0]
            except Exception:
                self._target = bot.game_info.map_center

            if self.log:
                self.log.emit(
                    "scout_started",
                    {"t": round(now, 2), "scv_tag": self._scv_tag, "mission_id": self.mission_id},
                )
            self.awareness.emit("scout_started", now=now, data={"scv_tag": self._scv_tag, "mission_id": self.mission_id})
            self._active("scout_started")

        scv = bot.units.find_by_tag(self._scv_tag)
        if scv is None:
            try:
                self.body.release_owner(task_id=self.mission_id)
            except Exception:
                pass

            self._done("unit_missing")
            self.awareness.emit("scout_lost", now=now, data={"mission_id": self.mission_id})
            return TaskResult.failed("unit_missing", retry_after_s=20.0)

        try:
            self.body.touch(task_id=self.mission_id, unit_tag=int(self._scv_tag), now=now)
        except Exception:
            pass

        if self._target:
            try:
                # Prefer enqueuing command if bot.do exists
                if hasattr(bot, "do"):
                    bot.do(scv.move(self._target))
                else:
                    # fallback: direct call (may be ignored by engine in some setups)
                    scv.move(self._target)
            except Exception:
                self._active("move_failed")
                return TaskResult.running("move_failed_retry")

        if self._target and scv.position.distance_to(self._target) <= self.see_radius:
            if not self.awareness.intel_scv_arrived_main(now=now):
                self.awareness.mark_scv_arrived_main(now=now)
                if self.log:
                    self.log.emit("scout_arrived_main", {"t": round(now, 2), "mission_id": self.mission_id})
                self.awareness.emit("scout_arrived_main", now=now, data={"mission_id": self.mission_id})

        if now - self._last_log_t >= self.log_every:
            self._last_log_t = now
            if self.log:
                self.log.emit(
                    "scout_status",
                    {
                        "t": round(now, 2),
                        "mission_id": self.mission_id,
                        "arrived": bool(self.awareness.intel_scv_arrived_main(now=now)),
                    },
                )

        self._active("scouting")
        return TaskResult.running("scouting")
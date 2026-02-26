# bot/tasks/reaper_scout_task.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.tasks.base_task import BaseTask, TaskTick, TaskResult


class ReaperScoutObjective(str, Enum):
    CONFIRM_NATURAL = "CONFIRM_NATURAL"
    CONFIRM_MAIN_RAMP = "CONFIRM_MAIN_RAMP"
    CONFIRM_MAIN = "CONFIRM_MAIN"
    MAP_CENTER = "MAP_CENTER"
    RETURN_HOME = "RETURN_HOME"


def _coerce_objective(obj: Any) -> ReaperScoutObjective:
    """
    Accept:
      - ReaperScoutObjective enum
      - raw value string: "CONFIRM_NATURAL"
      - qualified string: "ReaperScoutObjective.CONFIRM_NATURAL" (from str(enum))
    """
    if isinstance(obj, ReaperScoutObjective):
        return obj

    if isinstance(obj, str):
        s = obj.strip()
        # handle "ReaperScoutObjective.CONFIRM_NATURAL"
        if "." in s and s.startswith("ReaperScoutObjective."):
            s = s.split(".", 1)[1].strip()

        # prefer value lookup (Enum is str-based, so constructor matches values)
        try:
            return ReaperScoutObjective(s)
        except Exception:
            # also allow name lookup (in case caller passes "CONFIRM_NATURAL" as name)
            try:
                return ReaperScoutObjective[s]
            except Exception as e:
                raise ValueError(f"{obj!r} is not a valid ReaperScoutObjective") from e

    raise TypeError(f"objective must be ReaperScoutObjective or str, got {type(obj)}")


@dataclass
class ReaperScout(BaseTask):
    awareness: Awareness
    log: DevLogger | None = None

    objective: ReaperScoutObjective = ReaperScoutObjective.CONFIRM_NATURAL

    log_every: float = 6.0
    retreat_hp_frac: float = 0.40
    avoid_enemy_near_bases: int = 6
    arrive_radius_main: float = 4.5
    arrive_radius_nat: float = 7.0

    _last_log_t: float = field(default=0.0, init=False)
    _phase: int = field(default=0, init=False)

    def __init__(
        self,
        *,
        awareness: Awareness,
        log: DevLogger | None = None,
        objective: ReaperScoutObjective | str = ReaperScoutObjective.CONFIRM_NATURAL,
        log_every: float = 6.0,
        retreat_hp_frac: float = 0.40,
        arrive_radius_main: float = 4.5,
        arrive_radius_nat: float = 7.0,
    ):
        super().__init__(task_id="reaper_scout", domain="INTEL", commitment=7)
        self.awareness = awareness
        self.log = log

        # FIX: robust enum coercion
        self.objective = _coerce_objective(objective)

        self.log_every = float(log_every)
        self.retreat_hp_frac = float(retreat_hp_frac)
        self.arrive_radius_main = float(arrive_radius_main)
        self.arrive_radius_nat = float(arrive_radius_nat)
        self._last_log_t = 0.0
        self._phase = 0

    def evaluate(self, bot, attention: Attention) -> int:
        return 25

    def _enemy_main(self, bot) -> Point2:
        return bot.enemy_start_locations[0]

    def _enemy_natural(self, bot) -> Point2:
        enemy_main = self._enemy_main(bot)
        exps = list(getattr(bot, "expansion_locations_list", []) or [])
        if not exps:
            raise RuntimeError("expansion_locations_list unavailable for enemy natural computation")
        exps_sorted = sorted(exps, key=lambda p: p.distance_to(enemy_main))
        if len(exps_sorted) < 2:
            return exps_sorted[0]
        return exps_sorted[1]

    def _map_center(self, bot) -> Point2:
        gi = getattr(bot, "game_info", None)
        if gi is None:
            raise RuntimeError("game_info unavailable for map center")
        return gi.map_center

    def _log_tick(self, *, now: float, reason: str, tag: int, pos: Point2) -> None:
        if not self.log:
            return
        if (now - float(self._last_log_t)) < float(self.log_every):
            return
        self._last_log_t = float(now)
        self.log.emit(
            "reaper_scout_tick",
            {
                "t": round(float(now), 2),
                "mission_id": str(self.mission_id or ""),
                "tag": int(tag),
                "objective": str(self.objective.value),
                "phase": int(self._phase),
                "reason": str(reason),
                "pos": [round(float(pos.x), 1), round(float(pos.y), 1)],
            },
        )

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        now = float(tick.time)

        if not isinstance(self.mission_id, str) or not self.mission_id:
            return TaskResult.failed("unbound_mission")

        if not isinstance(self.assigned_tags, list) or len(self.assigned_tags) != 1:
            return TaskResult.failed("expected_exactly_1_assigned_tag")

        tag = int(self.assigned_tags[0])
        unit = bot.units.find_by_tag(tag)
        if unit is None:
            return TaskResult.failed("assigned_unit_missing")

        if unit.type_id != U.REAPER:
            return TaskResult.failed("assigned_unit_not_reaper")

        if bool(attention.combat.threatened) and int(attention.combat.enemy_count_near_bases) >= int(self.avoid_enemy_near_bases):
            unit.move(bot.start_location)
            self._active("retreat_home_under_threat")
            self._log_tick(now=now, reason="home_under_threat", tag=tag, pos=unit.position)
            return TaskResult.running("retreat_home_under_threat")

        hp_frac = float(unit.health_percentage) if hasattr(unit, "health_percentage") else 1.0
        if hp_frac <= float(self.retreat_hp_frac):
            unit.move(bot.start_location)
            self._active("retreat_low_hp")
            self._log_tick(now=now, reason="low_hp", tag=tag, pos=unit.position)
            return TaskResult.running("retreat_low_hp")

        if not self.awareness.intel_reaper_scout_dispatched(now=now):
            self.awareness.mark_reaper_scout_dispatched(now=now)

        if self.objective == ReaperScoutObjective.CONFIRM_NATURAL:
            nat = self._enemy_natural(bot)
            if self._phase == 0:
                if unit.distance_to(nat) <= float(self.arrive_radius_nat):
                    self._phase = 1
                else:
                    unit.move(nat)
                    self._active("move_enemy_natural")
                    self._log_tick(now=now, reason="to_natural", tag=tag, pos=unit.position)
                    return TaskResult.running("move_enemy_natural")

            main = self._enemy_main(bot)
            if unit.distance_to(main) <= float(self.arrive_radius_main):
                self.awareness.mark_reaper_scout_done(now=now)
                self._done("confirmed_natural_then_peeked_main")
                return TaskResult.done("confirmed_natural_then_peeked_main")

            unit.move(main)
            self._active("peek_enemy_main")
            self._log_tick(now=now, reason="peek_main", tag=tag, pos=unit.position)
            return TaskResult.running("peek_enemy_main")

        if self.objective == ReaperScoutObjective.CONFIRM_MAIN_RAMP:
            target = self._enemy_main(bot)
            if unit.distance_to(target) <= float(self.arrive_radius_main):
                self.awareness.mark_reaper_scout_done(now=now)
                self._done("peeked_enemy_main")
                return TaskResult.done("peeked_enemy_main")

            unit.move(target)
            self._active("move_enemy_main")
            self._log_tick(now=now, reason="to_main", tag=tag, pos=unit.position)
            return TaskResult.running("move_enemy_main")

        if self.objective == ReaperScoutObjective.MAP_CENTER:
            mc = self._map_center(bot)
            unit.move(mc)
            self._active("move_map_center")
            self._log_tick(now=now, reason="to_center", tag=tag, pos=unit.position)
            self.awareness.mark_reaper_scout_done(now=now)
            self._done("moved_map_center")
            return TaskResult.done("moved_map_center")

        if self.objective == ReaperScoutObjective.RETURN_HOME:
            unit.move(bot.start_location)
            self._active("return_home")
            self._log_tick(now=now, reason="return", tag=tag, pos=unit.position)
            self.awareness.mark_reaper_scout_done(now=now)
            self._done("returned_home")
            return TaskResult.done("returned_home")

        mc = self._map_center(bot)
        unit.move(mc)
        self._active("move_map_center_default")
        self._log_tick(now=now, reason="default_center", tag=tag, pos=unit.position)
        return TaskResult.running("move_map_center_default")

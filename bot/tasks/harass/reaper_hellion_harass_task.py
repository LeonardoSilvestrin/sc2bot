from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class ReaperHellionHarass(BaseTask):
    awareness: Awareness
    log: DevLogger | None = None
    preferred_target: Point2 | None = None
    max_harass_s: float = 70.0
    regroup_radius: float = 5.5
    retreat_reaper_hp_frac: float = 0.55
    retreat_hellion_hp_frac: float = 0.40
    commit_window_s: float = 4.0
    commit_min_can_win: int = 5
    commit_min_can_win_with_workers: int = 4
    commit_workers_threshold: int = 3
    retreat_loss_floor: int = 2

    _phase: int = field(default=0, init=False)
    _started_at: float = field(default=-1.0, init=False)
    _last_log_t: float = field(default=0.0, init=False)
    _commit_until: float = field(default=0.0, init=False)

    def __init__(self, *, awareness: Awareness, log: DevLogger | None = None, preferred_target: Point2 | None = None):
        super().__init__(task_id="reaper_hellion_harass", domain="HARASS", commitment=8)
        self.awareness = awareness
        self.log = log
        self.preferred_target = preferred_target

    def evaluate(self, bot, attention: Attention) -> int:
        return 70

    def _enemy_main(self, bot) -> Point2:
        return bot.enemy_start_locations[0]

    def _enemy_natural(self, bot) -> Point2:
        enemy_main = self._enemy_main(bot)
        exps = list(getattr(bot, "expansion_locations_list", []) or [])
        if not exps:
            return enemy_main
        # Robust natural detection: ignore the main point itself if present in list.
        exps_no_main = [p for p in exps if float(p.distance_to(enemy_main)) > 5.0]
        if not exps_no_main:
            exps_no_main = exps
        exps_sorted = sorted(exps_no_main, key=lambda p: p.distance_to(enemy_main))
        return exps_sorted[0]

    def _our_natural(self, bot) -> Point2:
        try:
            return bot.mediator.get_own_nat
        except Exception:
            return bot.start_location

    def _log_tick(self, *, now: float, reason: str, reaper_tag: int, hellion_count: int) -> None:
        if self.log is None:
            return
        if (float(now) - float(self._last_log_t)) < 2.5:
            return
        self._last_log_t = float(now)
        self.log.emit(
            "reaper_hellion_harass_tick",
            {
                "t": round(float(now), 2),
                "mission_id": str(self.mission_id or ""),
                "phase": int(self._phase),
                "reason": str(reason),
                "reaper_tag": int(reaper_tag),
                "hellions": int(hellion_count),
            },
            meta={"module": "task", "component": "task.reaper_hellion_harass"},
        )

    def _is_unit_safe(self, bot, unit) -> bool:
        try:
            grid = bot.mediator.get_ground_grid
            return bool(bot.mediator.is_position_safe(grid=grid, position=unit.position, weight_safety_limit=1.5))
        except Exception:
            return True

    @staticmethod
    def _can_attack_ground(enemy) -> bool:
        try:
            return bool(getattr(enemy, "can_attack_ground", False))
        except Exception:
            return False

    def _mission_threat(self, attention: Attention):
        if not isinstance(self.mission_id, str) or not self.mission_id:
            return None
        mts = getattr(attention, "unit_threats", None)
        if mts is None:
            return None
        for m in getattr(mts, "missions", ()) or ():
            if str(getattr(m, "mission_id", "")) == str(self.mission_id):
                return m
        return None

    def _should_commit(self, *, now: float, mission_threat) -> bool:
        if mission_threat is None:
            return False
        can_win_value = getattr(mission_threat, "can_win_value", None)
        if can_win_value is not None:
            if int(can_win_value) >= int(self.commit_min_can_win):
                self._commit_until = max(float(self._commit_until), float(now) + float(self.commit_window_s))
                return True
            workers = int(getattr(mission_threat, "worker_targets", 0) or 0)
            if workers >= int(self.commit_workers_threshold) and int(can_win_value) >= int(self.commit_min_can_win_with_workers):
                self._commit_until = max(float(self._commit_until), float(now) + float(self.commit_window_s))
                return True
        return False

    def _should_retreat_with_micro(self, *, bot, reaper, hellions: list, now: float, mission_threat) -> bool:
        if reaper is not None:
            if float(getattr(reaper, "health_percentage", 1.0) or 1.0) <= float(self.retreat_reaper_hp_frac):
                return True
        for h in hellions:
            if float(getattr(h, "health_percentage", 1.0) or 1.0) <= float(self.retreat_hellion_hp_frac):
                return True

        # During a short commit window, only retreat if the fight outlook is catastrophic.
        if float(now) < float(self._commit_until):
            if mission_threat is not None:
                can_win_value = getattr(mission_threat, "can_win_value", None)
                if can_win_value is not None:
                    if int(can_win_value) <= int(self.retreat_loss_floor):
                        units_in_danger = int(getattr(mission_threat, "units_in_danger", 0) or 0)
                        unit_count = int(getattr(mission_threat, "unit_count", 0) or 0)
                        if units_in_danger >= max(1, unit_count // 2):
                            return True
            return False

        if mission_threat is not None:
            can_win_value = getattr(mission_threat, "can_win_value", None)
            if can_win_value is not None:
                if int(can_win_value) >= int(self.commit_min_can_win):
                    return False
                workers = int(getattr(mission_threat, "worker_targets", 0) or 0)
                if workers >= int(self.commit_workers_threshold) and int(can_win_value) >= int(self.commit_min_can_win_with_workers):
                    return False
                if int(can_win_value) <= int(self.retreat_loss_floor):
                    return True

        anchor = reaper if reaper is not None else (hellions[0] if hellions else None)
        if anchor is None:
            return True
        if not self._is_unit_safe(bot, anchor):
            return True
        close_enemy = bot.enemy_units.closer_than(10.0, anchor.position)
        dangerous = sum(1 for e in close_enemy if self._can_attack_ground(e))
        if reaper is not None and not hellions:
            # Solo reaper should be extra conservative.
            return dangerous >= 2
        return dangerous >= 4

    @staticmethod
    def _closest_worker(unit, enemies):
        workers = enemies.of_type({U.SCV, U.PROBE, U.DRONE, U.MULE})
        if workers.amount == 0:
            return None
        return workers.closest_to(unit)

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        now = float(tick.time)
        if self._started_at < 0.0:
            self._started_at = float(now)

        bound_err = self.require_mission_bound(min_tags=1)
        if bound_err is not None:
            return bound_err

        units = [bot.units.find_by_tag(int(t)) for t in self.assigned_tags]
        units = [u for u in units if u is not None]
        reapers = [u for u in units if u.type_id == U.REAPER]
        hellions = [u for u in units if u.type_id == U.HELLION]

        reaper = reapers[0] if reapers else None

        if reaper is None and len(hellions) < 1:
            return TaskResult.failed("no_harass_units_alive")

        if (float(now) - float(self._started_at)) >= float(self.max_harass_s):
            self._phase = 2

        mission_threat = self._mission_threat(attention)
        self._should_commit(now=now, mission_threat=mission_threat)

        if self._phase < 2 and self._should_retreat_with_micro(
            bot=bot,
            reaper=reaper,
            hellions=hellions,
            now=now,
            mission_threat=mission_threat,
        ):
            self._phase = 2

        enemy_main = self._enemy_main(bot)
        base_target = self.preferred_target or self._enemy_natural(bot)
        staging = base_target.towards(bot.game_info.map_center, 7.0)
        harass_target = base_target.towards(enemy_main, 2.0)
        retreat_target = self._our_natural(bot)

        if self._phase == 0:
            group = ([reaper] if reaper is not None else []) + hellions
            for u in group:
                u.move(staging)
            if group and all(float(u.distance_to(staging)) <= float(self.regroup_radius) for u in group):
                self._phase = 1
            self._active("harass_regroup")
            self._log_tick(now=now, reason="regroup", reaper_tag=int(reaper.tag) if reaper is not None else -1, hellion_count=len(hellions))
            return TaskResult.running("harass_regroup")

        if self._phase == 1:
            local_enemies = bot.enemy_units.closer_than(12.0, harass_target)
            if reaper is not None:
                r_target = self._closest_worker(reaper, local_enemies)
                if r_target is not None:
                    reaper.attack(r_target)
                else:
                    reaper.move(harass_target)

            for h in hellions:
                h_target = self._closest_worker(h, local_enemies)
                if h_target is not None:
                    h.attack(h_target)
                else:
                    h.move(harass_target)

            self._active("harass_enemy_natural")
            self._log_tick(now=now, reason="harass", reaper_tag=int(reaper.tag) if reaper is not None else -1, hellion_count=len(hellions))
            return TaskResult.running("harass_enemy_natural")

        group = ([reaper] if reaper is not None else []) + hellions
        for u in group:
            u.move(retreat_target)

        if group and all(float(u.distance_to(retreat_target)) <= 8.0 for u in group):
            self.awareness.mem.set(K("ops", "harass", "reaper_hellion", "done"), value=True, now=now, ttl=None)
            self.awareness.mem.set(K("ops", "harass", "reaper_hellion", "done_at"), value=float(now), now=now, ttl=None)
            self._done("reaper_hellion_harass_done")
            return TaskResult.done("reaper_hellion_harass_done")

        self._active("harass_exit_safe")
        self._log_tick(now=now, reason="retreat", reaper_tag=int(reaper.tag) if reaper is not None else -1, hellion_count=len(hellions))
        return TaskResult.running("harass_exit_safe")

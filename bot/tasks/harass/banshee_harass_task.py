from __future__ import annotations

from dataclasses import dataclass, field
import math

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2
from sc2.units import Units

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class BansheeHarass(BaseTask):
    awareness: Awareness
    log: DevLogger | None = None
    preferred_target: Point2 | None = None
    max_harass_s: float = 70.0
    regroup_radius: float = 7.0
    retreat_hp_frac: float = 0.45
    kite_step: float = 2.8
    banshee_attack_range: float = 6.0
    stutter_fire_cooldown_s: float = 0.2
    force_retreat_anti_air_count: int = 4
    route_engage_radius: float = 11.0
    route_engage_min_can_win: int = 5
    cloak_energy_min: float = 25.0
    cloak_command_cooldown_s: float = 0.9

    _phase: int = field(default=0, init=False)
    _started_at: float = field(default=-1.0, init=False)
    _last_log_t: float = field(default=0.0, init=False)
    _last_hp: dict[int, float] = field(default_factory=dict, init=False)
    _last_cloak_cmd_t: dict[int, float] = field(default_factory=dict, init=False)

    def __init__(self, *, awareness: Awareness, log: DevLogger | None = None, preferred_target: Point2 | None = None):
        super().__init__(task_id="banshee_harass", domain="HARASS", commitment=8)
        self.awareness = awareness
        self.log = log
        self.preferred_target = preferred_target
        self._last_hp = {}
        self._last_cloak_cmd_t = {}

    def evaluate(self, bot, attention: Attention) -> int:
        return 68

    def _enemy_main(self, bot) -> Point2:
        return bot.enemy_start_locations[0]

    def _enemy_natural(self, bot) -> Point2:
        enemy_main = self._enemy_main(bot)
        exps = list(getattr(bot, "expansion_locations_list", []) or [])
        if not exps:
            return enemy_main
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

    @staticmethod
    def _closest_worker(unit, enemies):
        workers = enemies.of_type({U.SCV, U.PROBE, U.DRONE, U.MULE})
        if workers.amount == 0:
            return None
        return workers.closest_to(unit)

    @staticmethod
    def _can_attack_air(enemy) -> bool:
        try:
            return bool(getattr(enemy, "can_attack_air", False))
        except Exception:
            return False

    @staticmethod
    def _is_detector(enemy) -> bool:
        try:
            return bool(getattr(enemy, "is_detector", False))
        except Exception:
            return False

    def _log_tick(self, *, now: float, reason: str, banshees: int) -> None:
        if self.log is None:
            return
        if (float(now) - float(self._last_log_t)) < 2.5:
            return
        self._last_log_t = float(now)
        self.log.emit(
            "banshee_harass_tick",
            {
                "t": round(float(now), 2),
                "mission_id": str(self.mission_id or ""),
                "phase": int(self._phase),
                "reason": str(reason),
                "banshees": int(banshees),
            },
            meta={"module": "task", "component": "task.banshee_harass"},
        )

    @staticmethod
    def _retreat_point(unit_pos: Point2, threat_pos: Point2, step: float) -> Point2:
        dx = float(unit_pos.x) - float(threat_pos.x)
        dy = float(unit_pos.y) - float(threat_pos.y)
        n = math.hypot(dx, dy)
        if n <= 1e-6:
            return Point2((float(unit_pos.x), float(unit_pos.y)))
        ux = dx / n
        uy = dy / n
        return Point2((float(unit_pos.x) + (ux * float(step)), float(unit_pos.y) + (uy * float(step))))

    def _stutter_attack(self, *, banshee, local_enemies, fallback_target: Point2) -> None:
        target = self._closest_worker(banshee, local_enemies)
        if target is None and local_enemies.amount > 0:
            target = local_enemies.closest_to(banshee)
        if target is None:
            banshee.move(fallback_target)
            return
        dist = float(banshee.distance_to(target))
        wc = float(getattr(banshee, "weapon_cooldown", 0.0) or 0.0)
        if dist <= float(self.banshee_attack_range) and wc <= float(self.stutter_fire_cooldown_s):
            banshee.attack(target)
            return
        if dist <= float(self.banshee_attack_range) and wc > float(self.stutter_fire_cooldown_s):
            kite_to = self._retreat_point(banshee.position, target.position, float(self.kite_step))
            banshee.move(kite_to)
            return
        banshee.move(target.position)

    def _dynamic_retreat_hp_frac(self, *, banshee_count: int) -> float:
        # Early/small harass groups should preserve units more aggressively.
        if int(banshee_count) <= 1:
            return max(float(self.retreat_hp_frac), 0.72)
        if int(banshee_count) == 2:
            return max(float(self.retreat_hp_frac), 0.64)
        if int(banshee_count) == 3:
            return max(float(self.retreat_hp_frac), 0.56)
        return float(self.retreat_hp_frac)

    def _dynamic_route_engage_min_can_win(self, *, banshee_count: int) -> int:
        if int(banshee_count) <= 2:
            return max(int(self.route_engage_min_can_win), 6)
        return int(self.route_engage_min_can_win)

    def _dynamic_force_retreat_anti_air_count(self, *, banshee_count: int) -> int:
        # Smaller groups retreat with fewer enemy anti-air units.
        if int(banshee_count) <= 1:
            return 2
        if int(banshee_count) == 2:
            return 3
        return int(self.force_retreat_anti_air_count)

    def _route_should_engage(self, *, bot, banshees: list, local_enemies) -> bool:
        if not banshees or local_enemies.amount <= 0:
            return False
        workers = local_enemies.of_type({U.SCV, U.PROBE, U.DRONE, U.MULE})
        anti_air = local_enemies.filter(lambda e: self._can_attack_air(e))
        if int(workers.amount) >= 1 and int(anti_air.amount) <= 2:
            return True
        if int(anti_air.amount) <= 0:
            return False
        can_win_fight = getattr(bot.mediator, "can_win_fight", None)
        if not callable(can_win_fight):
            return False
        try:
            res = can_win_fight(
                own_units=Units(banshees, bot),
                enemy_units=anti_air,
                timing_adjust=True,
                good_positioning=True,
                workers_do_no_damage=True,
            )
            can_win_value = int(getattr(res, "value", int(res)))
            min_can_win = self._dynamic_route_engage_min_can_win(banshee_count=len(banshees))
            return int(can_win_value) >= int(min_can_win)
        except Exception:
            return False

    def _update_cloak_state(self, *, banshee, local_enemies, now: float) -> None:
        tag = int(getattr(banshee, "tag", 0) or 0)
        if tag <= 0:
            return
        hp = float(getattr(banshee, "health", 0.0) or 0.0)
        prev_hp = float(self._last_hp.get(tag, hp))
        took_hit = float(hp) < float(prev_hp) - 1e-3
        self._last_hp[tag] = float(hp)

        anti_air = [e for e in local_enemies if self._can_attack_air(e)]
        detectors = [e for e in local_enemies if self._is_detector(e)]
        aa_threat_near = any(float(banshee.distance_to(e)) <= 8.0 for e in anti_air)
        detector_near = any(float(banshee.distance_to(e)) <= 11.0 for e in detectors)
        is_cloaked = bool(getattr(banshee, "is_cloaked", False))
        energy = float(getattr(banshee, "energy", 0.0) or 0.0)
        last_cmd_t = float(self._last_cloak_cmd_t.get(tag, -9999.0))
        can_send_cmd = (float(now) - float(last_cmd_t)) >= float(self.cloak_command_cooldown_s)

        should_cloak_on = bool((took_hit or aa_threat_near) and (not detector_near) and energy >= float(self.cloak_energy_min))
        should_cloak_off = bool((not aa_threat_near) or detector_near)

        if should_cloak_on and (not is_cloaked) and can_send_cmd:
            banshee(AbilityId.BEHAVIOR_CLOAKON_BANSHEE)
            self._last_cloak_cmd_t[tag] = float(now)
            return
        if should_cloak_off and is_cloaked and can_send_cmd:
            banshee(AbilityId.BEHAVIOR_CLOAKOFF_BANSHEE)
            self._last_cloak_cmd_t[tag] = float(now)
            return

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        now = float(tick.time)
        if self._started_at < 0.0:
            self._started_at = float(now)

        bound_err = self.require_mission_bound(min_tags=1)
        if bound_err is not None:
            return bound_err

        banshees = [bot.units.find_by_tag(int(t)) for t in self.assigned_tags]
        banshees = [u for u in banshees if u is not None and u.type_id == U.BANSHEE]
        if not banshees:
            return TaskResult.failed("no_banshee_alive")
        alive_tags = {int(getattr(b, "tag", 0) or 0) for b in banshees}
        self._last_hp = {k: v for k, v in self._last_hp.items() if k in alive_tags}
        self._last_cloak_cmd_t = {k: v for k, v in self._last_cloak_cmd_t.items() if k in alive_tags}

        if (float(now) - float(self._started_at)) >= float(self.max_harass_s):
            self._phase = 2

        retreat_hp_frac = self._dynamic_retreat_hp_frac(banshee_count=len(banshees))
        if any(float(getattr(b, "health_percentage", 1.0) or 1.0) <= float(retreat_hp_frac) for b in banshees):
            self._phase = 2

        enemy_main = self._enemy_main(bot)
        base_target = self.preferred_target or self._enemy_natural(bot)
        staging = base_target.towards(bot.game_info.map_center, 9.0)
        harass_target = base_target.towards(enemy_main, 2.0)
        retreat_target = self._our_natural(bot)

        if self._phase == 0:
            cx = sum(float(b.position.x) for b in banshees) / float(len(banshees))
            cy = sum(float(b.position.y) for b in banshees) / float(len(banshees))
            center = Point2((cx, cy))
            local_enemies = bot.enemy_units.closer_than(float(self.route_engage_radius), center)
            if self._route_should_engage(bot=bot, banshees=banshees, local_enemies=local_enemies):
                for b in banshees:
                    local_b = local_enemies.closer_than(11.0, b.position)
                    self._update_cloak_state(banshee=b, local_enemies=local_b, now=now)
                    self._stutter_attack(banshee=b, local_enemies=local_b, fallback_target=staging)
                self._active("banshee_route_skirmish")
                self._log_tick(now=now, reason="route_skirmish", banshees=len(banshees))
                return TaskResult.running("banshee_route_skirmish")
            for b in banshees:
                local_b = bot.enemy_units.closer_than(11.0, b.position)
                self._update_cloak_state(banshee=b, local_enemies=local_b, now=now)
                b.move(staging)
            if all(float(b.distance_to(staging)) <= float(self.regroup_radius) for b in banshees):
                self._phase = 1
            self._active("banshee_regroup")
            self._log_tick(now=now, reason="regroup", banshees=len(banshees))
            return TaskResult.running("banshee_regroup")

        if self._phase == 1:
            force_retreat_aa_count = self._dynamic_force_retreat_anti_air_count(banshee_count=len(banshees))
            for b in banshees:
                local_enemies = bot.enemy_units.closer_than(11.0, b.position)
                self._update_cloak_state(banshee=b, local_enemies=local_enemies, now=now)
                anti_air = [e for e in local_enemies if self._can_attack_air(e)]
                if len(anti_air) >= int(force_retreat_aa_count):
                    self._phase = 2
                    break
                if anti_air:
                    nearest_aa = min(anti_air, key=lambda e: float(b.distance_to(e)))
                    nearest_dist = float(b.distance_to(nearest_aa))
                    if nearest_dist <= 7.5 and float(getattr(b, "weapon_cooldown", 0.0) or 0.0) > float(self.stutter_fire_cooldown_s):
                        b.move(self._retreat_point(b.position, nearest_aa.position, float(self.kite_step)))
                        continue
                self._stutter_attack(banshee=b, local_enemies=local_enemies, fallback_target=harass_target)
            if self._phase == 1:
                self._active("banshee_harass")
                self._log_tick(now=now, reason="harass", banshees=len(banshees))
                return TaskResult.running("banshee_harass")

        for b in banshees:
            local_enemies = bot.enemy_units.closer_than(11.0, b.position)
            self._update_cloak_state(banshee=b, local_enemies=local_enemies, now=now)
            b.move(retreat_target)
        if all(float(b.distance_to(retreat_target)) <= 9.0 for b in banshees):
            self.awareness.mem.set(K("ops", "harass", "banshee", "done"), value=True, now=now, ttl=None)
            self.awareness.mem.set(K("ops", "harass", "banshee", "done_at"), value=float(now), now=now, ttl=None)
            self._done("banshee_harass_done")
            return TaskResult.done("banshee_harass_done")

        self._active("banshee_exit_safe")
        self._log_tick(now=now, reason="retreat", banshees=len(banshees))
        return TaskResult.running("banshee_exit_safe")


from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2
from sc2.units import Units

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


_DROP_TROOPER_TYPES = {U.MARINE, U.MARAUDER}


@dataclass
class MedivacDropHarassTask(BaseTask):
    awareness: Awareness
    target_locations: list[Point2]
    log: DevLogger | None = None
    max_harass_s: float = 110.0
    load_radius: float = 3.0
    move_to_load_radius: float = 8.0
    staging_distance: float = 11.0
    drop_arrival_radius: float = 7.5
    unload_radius: float = 2.5
    medivac_hold_offset: float = 5.5
    retreat_reboard_radius: float = 7.0
    ground_regroup_radius: float = 7.0
    switch_target_cooldown_s: float = 5.0
    switch_target_after_s: float = 10.0
    hard_retreat_urgency: int = 20
    route_switch_anti_air: int = 2
    drop_switch_anti_air: int = 3
    force_retreat_anti_air: int = 5
    medivac_retreat_hp_frac: float = 0.42
    trooper_retreat_hp_frac: float = 0.35
    mission_switch_can_win: int = 4
    mission_retreat_can_win: int = 2

    _started_at: float = field(default=-1.0, init=False)
    _target_idx: int = field(default=0, init=False)
    _last_target_switch_t: float = field(default=-9999.0, init=False)
    _landed_at_target_t: float = field(default=-1.0, init=False)
    _phase: str = field(default="LOAD", init=False)
    _last_log_t: float = field(default=0.0, init=False)

    def __init__(
        self,
        *,
        awareness: Awareness,
        target_locations: list[Point2],
        log: DevLogger | None = None,
    ) -> None:
        super().__init__(task_id="medivac_drop_harass", domain="HARASS", commitment=14)
        self.awareness = awareness
        self.target_locations = [Point2((float(p.x), float(p.y))) for p in list(target_locations or []) if p is not None]
        self.log = log

    def evaluate(self, bot, attention: Attention) -> int:
        _ = bot, attention
        return 72

    @staticmethod
    def _enemy_main(bot) -> Point2:
        return bot.enemy_start_locations[0]

    def _our_natural(self, bot) -> Point2:
        try:
            return bot.mediator.get_own_nat
        except Exception:
            return bot.start_location

    @staticmethod
    def _mineral_line_center(bot, base_pos: Point2) -> Point2:
        try:
            mfs = bot.mineral_field.closer_than(12.0, base_pos)
            if mfs.amount > 0:
                x = sum(float(m.position.x) for m in mfs) / float(mfs.amount)
                y = sum(float(m.position.y) for m in mfs) / float(mfs.amount)
                return Point2((x, y))
        except Exception:
            pass
        return base_pos

    @staticmethod
    def _cargo_cost(unit) -> int:
        if unit is None:
            return 0
        return 2 if unit.type_id == U.MARAUDER else 1

    @staticmethod
    def _can_attack_air(enemy) -> bool:
        try:
            return bool(getattr(enemy, "can_attack_air", False))
        except Exception:
            return False

    @staticmethod
    def _can_attack_ground(enemy) -> bool:
        try:
            return bool(getattr(enemy, "can_attack_ground", False))
        except Exception:
            return False

    def _log_tick(self, *, now: float, reason: str, medivacs: int, troopers: int) -> None:
        if self.log is None:
            return
        if (float(now) - float(self._last_log_t)) < 2.5:
            return
        self._last_log_t = float(now)
        self.log.emit(
            "medivac_drop_harass_tick",
            {
                "t": round(float(now), 2),
                "mission_id": str(self.mission_id or ""),
                "phase": str(self._phase),
                "reason": str(reason),
                "target_idx": int(self._target_idx),
                "medivacs": int(medivacs),
                "troopers": int(troopers),
            },
            meta={"module": "task", "component": "task.medivac_drop_harass"},
        )

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

    def _mission_threat_state(self, *, now: float) -> dict:
        state = self.awareness.mem.get(K("intel", "mission", str(self.mission_id or ""), "threat", "state"), now=now, default={}) or {}
        return state if isinstance(state, dict) else {}

    def _can_switch_target(self, *, now: float) -> bool:
        return len(self.target_locations) > 1 and (float(now) - float(self._last_target_switch_t)) >= float(self.switch_target_cooldown_s)

    def _advance_target(self, *, now: float, reason: str) -> bool:
        if not self._can_switch_target(now=now):
            return False
        self._target_idx = int((int(self._target_idx) + 1) % max(1, len(self.target_locations)))
        self._last_target_switch_t = float(now)
        self._landed_at_target_t = -1.0
        self._phase = "LOAD"
        self._active(f"switch_target:{reason}")
        return True

    def _target_base(self) -> Point2:
        if not self.target_locations:
            raise RuntimeError("medivac_drop_requires_target_locations")
        return self.target_locations[int(self._target_idx) % len(self.target_locations)]

    def _target_drop_pos(self, bot) -> Point2:
        return self._mineral_line_center(bot, self._target_base())

    def _target_staging_pos(self, bot) -> Point2:
        drop_pos = self._target_drop_pos(bot)
        return drop_pos.towards(bot.game_info.map_center, float(self.staging_distance))

    def _home_retreat_pos(self, bot) -> Point2:
        nat = self._our_natural(bot)
        return nat.towards(bot.start_location, 3.5)

    def _drop_exit_pos(self, bot) -> Point2:
        drop_pos = self._target_drop_pos(bot)
        return drop_pos.towards(self._home_retreat_pos(bot), float(self.medivac_hold_offset))

    @staticmethod
    def _center(units: list) -> Point2 | None:
        if not units:
            return None
        x = sum(float(u.position.x) for u in units) / float(len(units))
        y = sum(float(u.position.y) for u in units) / float(len(units))
        return Point2((x, y))

    def _air_safe(self, *, bot, pos: Point2, limit: float = 2.2) -> bool:
        try:
            return bool(bot.mediator.is_position_safe(grid=bot.mediator.get_air_grid, position=pos, weight_safety_limit=float(limit)))
        except Exception:
            return True

    def _anti_air_enemies(self, *, bot, pos: Point2, radius: float) -> list:
        return [e for e in list(bot.enemy_units.closer_than(float(radius), pos)) if self._can_attack_air(e)]

    def _ground_enemies(self, *, bot, pos: Point2, radius: float) -> list:
        return [e for e in list(bot.enemy_units.closer_than(float(radius), pos)) if not bool(getattr(e, "is_flying", False))]

    def _route_is_dangerous(self, *, bot, medivacs: list, staging: Point2) -> bool:
        if not medivacs:
            return True
        center = self._center(medivacs) or medivacs[0].position
        if not self._air_safe(bot=bot, pos=staging):
            return True
        aa_near = self._anti_air_enemies(bot=bot, pos=center, radius=10.0)
        return int(len(aa_near)) >= int(self.route_switch_anti_air)

    def _drop_zone_is_dangerous(self, *, bot, drop_pos: Point2) -> bool:
        if not self._air_safe(bot=bot, pos=drop_pos):
            return True
        aa_near = self._anti_air_enemies(bot=bot, pos=drop_pos, radius=11.0)
        return int(len(aa_near)) >= int(self.drop_switch_anti_air)

    def _should_retreat(self, *, attention: Attention, mission_threat, threat_state: dict, medivacs: list, troopers: list) -> bool:
        if int(attention.combat.primary_urgency) >= int(self.hard_retreat_urgency):
            return True
        if any(float(getattr(m, "health_percentage", 1.0) or 1.0) <= float(self.medivac_retreat_hp_frac) for m in medivacs):
            return True
        if troopers and all(float(getattr(u, "health_percentage", 1.0) or 1.0) <= float(self.trooper_retreat_hp_frac) for u in troopers):
            return True
        if bool(threat_state.get("retreat_recommended", False)):
            return True
        can_win_value = getattr(mission_threat, "can_win_value", None)
        if can_win_value is not None and int(can_win_value) <= int(self.mission_retreat_can_win):
            return True
        return False

    def _should_switch_target(self, *, mission_threat, threat_state: dict) -> bool:
        if bool(threat_state.get("reinforce_needed", False)):
            return True
        can_win_value = getattr(mission_threat, "can_win_value", None)
        if can_win_value is not None and int(can_win_value) <= int(self.mission_switch_can_win):
            return True
        return False

    def _load_troopers(self, *, medivacs: list, troopers: list) -> bool:
        issued = False
        reserved_tags: set[int] = set()
        remaining_by_medivac: dict[int, int] = {
            int(getattr(m, "tag", 0) or 0): max(0, int(getattr(m, "cargo_max", 8) or 8) - int(getattr(m, "cargo_used", 0) or 0))
            for m in medivacs
        }
        for medivac in medivacs:
            medivac_tag = int(getattr(medivac, "tag", 0) or 0)
            remaining = int(remaining_by_medivac.get(medivac_tag, 0))
            if remaining <= 0:
                continue
            candidates = [
                u for u in troopers
                if not bool(getattr(u, "is_loaded", False)) and int(getattr(u, "tag", 0) or 0) not in reserved_tags
            ]
            candidates.sort(key=lambda u: float(u.distance_to(medivac)))
            used_now = 0
            for unit in candidates:
                unit_tag = int(getattr(unit, "tag", 0) or 0)
                cost = int(self._cargo_cost(unit))
                if cost > max(0, remaining - used_now):
                    continue
                if float(unit.distance_to(medivac)) <= float(self.load_radius):
                    unit(AbilityId.SMART, medivac)
                else:
                    unit.move(medivac.position)
                used_now += cost
                reserved_tags.add(unit_tag)
                issued = True
            remaining_by_medivac[medivac_tag] = max(0, remaining - used_now)
            if used_now <= 0 and candidates:
                medivac.move(candidates[0].position)
                issued = True
        return issued

    @staticmethod
    def _closest_worker(unit, enemies):
        workers = [e for e in enemies if e.type_id in {U.SCV, U.PROBE, U.DRONE, U.MULE}]
        if not workers:
            return None
        return min(workers, key=lambda e: float(unit.distance_to(e)))

    def _ground_can_commit(self, *, bot, troopers: list, local_enemies: list) -> bool:
        if not troopers or not local_enemies:
            return True
        ground_enemies = [e for e in local_enemies if self._can_attack_ground(e)]
        if not ground_enemies:
            return True
        can_win_fight = getattr(bot.mediator, "can_win_fight", None)
        if not callable(can_win_fight):
            return True
        try:
            res = can_win_fight(
                own_units=Units(troopers, bot),
                enemy_units=Units(ground_enemies, bot),
                timing_adjust=True,
                good_positioning=True,
                workers_do_no_damage=True,
            )
            return int(getattr(res, "value", int(res))) >= int(self.mission_switch_can_win)
        except Exception:
            return True

    def _harass_ground(self, *, bot, troopers: list, target: Point2, regroup: Point2) -> bool:
        issued = False
        local = self._ground_enemies(bot=bot, pos=target, radius=10.0)
        for unit in troopers:
            if bool(getattr(unit, "is_loaded", False)):
                continue
            close = [e for e in local if float(unit.distance_to(e)) <= 10.0]
            target_enemy = self._closest_worker(unit, close) if close else None
            if target_enemy is None and close:
                target_enemy = min(close, key=lambda e: float(unit.distance_to(e)))
            if target_enemy is not None:
                unit.attack(target_enemy)
            elif float(unit.distance_to(target)) > 2.5:
                unit.move(target)
            else:
                unit.attack(regroup)
            issued = True
        return issued

    def _recall_and_load(self, *, medivacs: list, troopers: list, fallback: Point2) -> bool:
        issued = False
        remaining_by_medivac: dict[int, int] = {
            int(getattr(m, "tag", 0) or 0): max(0, int(getattr(m, "cargo_max", 8) or 8) - int(getattr(m, "cargo_used", 0) or 0))
            for m in medivacs
        }
        for unit in troopers:
            if bool(getattr(unit, "is_loaded", False)):
                continue
            free_medivacs = [
                m for m in medivacs
                if int(remaining_by_medivac.get(int(getattr(m, "tag", 0) or 0), 0)) >= int(self._cargo_cost(unit))
            ]
            if free_medivacs:
                medivac = min(free_medivacs, key=lambda m: float(unit.distance_to(m)))
                medivac_tag = int(getattr(medivac, "tag", 0) or 0)
                if float(unit.distance_to(medivac)) <= float(self.load_radius):
                    unit(AbilityId.SMART, medivac)
                else:
                    unit.move(medivac.position)
                remaining_by_medivac[medivac_tag] = max(
                    0,
                    int(remaining_by_medivac.get(medivac_tag, 0)) - int(self._cargo_cost(unit)),
                )
                issued = True
            else:
                unit.move(fallback)
                issued = True
        for medivac in medivacs:
            medivac.move(fallback)
            issued = True
        return issued

    def _retreat_home(self, *, bot, medivacs: list, troopers: list) -> TaskResult:
        retreat = self._home_retreat_pos(bot)
        issued = self._recall_and_load(medivacs=medivacs, troopers=troopers, fallback=retreat)
        done = True
        for medivac in medivacs:
            if float(medivac.distance_to(retreat)) > 7.0:
                done = False
                break
        for unit in troopers:
            if bool(getattr(unit, "is_loaded", False)):
                continue
            if float(unit.distance_to(retreat)) > 8.0:
                done = False
                break
        self._phase = "RETREAT"
        if done:
            self._done("drop_retreated_home")
            return TaskResult.done("drop_retreated_home")
        self._active("drop_retreating")
        return TaskResult.running("drop_retreating" if issued else "drop_retreat_hold")

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        now = float(tick.time)
        if self._started_at < 0.0:
            self._started_at = float(now)
        if not self.target_locations:
            return TaskResult.failed("no_drop_targets")

        bound_err = self.require_mission_bound(min_tags=2)
        if bound_err is not None:
            return bound_err

        units = [bot.units.find_by_tag(int(t)) for t in self.assigned_tags]
        units = [u for u in units if u is not None]
        medivacs = [u for u in units if u.type_id == U.MEDIVAC]
        troopers = [u for u in units if u.type_id in _DROP_TROOPER_TYPES]
        if not medivacs:
            return TaskResult.failed("no_medivac_alive")
        if not troopers:
            return TaskResult.failed("no_drop_troopers_alive")

        mission_threat = self._mission_threat(attention)
        threat_state = self._mission_threat_state(now=now)
        if (float(now) - float(self._started_at)) >= float(self.max_harass_s):
            return self._retreat_home(bot=bot, medivacs=medivacs, troopers=troopers)
        if self._should_retreat(
            attention=attention,
            mission_threat=mission_threat,
            threat_state=threat_state,
            medivacs=medivacs,
            troopers=troopers,
        ):
            return self._retreat_home(bot=bot, medivacs=medivacs, troopers=troopers)

        target_base = self._target_base()
        drop_pos = self._target_drop_pos(bot)
        staging = self._target_staging_pos(bot)
        drop_exit = self._drop_exit_pos(bot)
        medivac_center = self._center(medivacs) or medivacs[0].position
        unloaded = [u for u in troopers if not bool(getattr(u, "is_loaded", False))]

        if not unloaded and self._route_is_dangerous(bot=bot, medivacs=medivacs, staging=staging):
            if self._advance_target(now=now, reason="route_intercepted"):
                target_base = self._target_base()
                drop_pos = self._target_drop_pos(bot)
                staging = self._target_staging_pos(bot)
                drop_exit = self._drop_exit_pos(bot)
            else:
                return self._retreat_home(bot=bot, medivacs=medivacs, troopers=troopers)

        if self._drop_zone_is_dangerous(bot=bot, drop_pos=drop_pos) and self._can_switch_target(now=now):
            if self._advance_target(now=now, reason="drop_zone_hot"):
                target_base = self._target_base()
                drop_pos = self._target_drop_pos(bot)
                staging = self._target_staging_pos(bot)
                drop_exit = self._drop_exit_pos(bot)

        # Medivacs cheios (sem espaço) não precisam esperar troopers restantes —
        # os troopers que ficarem de fora ficam atrás. Isso evita travar em LOAD
        # quando um trooper está preso ou inacessível.
        all_medivacs_full = all(
            int(getattr(m, "cargo_used", 0) or 0) >= int(getattr(m, "cargo_max", 8) or 8)
            for m in medivacs
        )
        load_timeout = (float(now) - float(self._started_at)) >= 20.0
        if self._landed_at_target_t < 0.0 and unloaded and not all_medivacs_full and not load_timeout:
            avg_trooper = self._center(unloaded) or unloaded[0].position
            if float(medivac_center.distance_to(avg_trooper)) > float(self.move_to_load_radius):
                for medivac in medivacs:
                    medivac.move(avg_trooper)
                self._phase = "LOAD"
                self._active("moving_to_load")
                self._log_tick(now=now, reason="moving_to_load", medivacs=len(medivacs), troopers=len(troopers))
                return TaskResult.running("moving_to_load")
            issued = self._load_troopers(medivacs=medivacs, troopers=troopers)
            self._phase = "LOAD"
            self._active("loading_drop")
            self._log_tick(now=now, reason="loading", medivacs=len(medivacs), troopers=len(troopers))
            return TaskResult.running("loading_drop" if issued else "loading_drop_hold")

        if float(medivac_center.distance_to(staging)) > float(self.drop_arrival_radius) and float(medivac_center.distance_to(drop_pos)) > 14.0:
            for medivac in medivacs:
                medivac.move(staging)
            self._phase = "STAGING"
            self._active("flying_to_staging")
            self._log_tick(now=now, reason="flying_to_staging", medivacs=len(medivacs), troopers=len(troopers))
            return TaskResult.running("flying_to_staging")

        if float(medivac_center.distance_to(drop_pos)) > float(self.drop_arrival_radius):
            for medivac in medivacs:
                medivac.move(drop_pos)
            self._phase = "DROP"
            self._active("flying_to_drop")
            self._log_tick(now=now, reason="flying_to_drop", medivacs=len(medivacs), troopers=len(troopers))
            return TaskResult.running("flying_to_drop")

        for medivac in medivacs:
            medivac(AbilityId.UNLOADALLAT_MEDIVAC, drop_pos)
            medivac.move(drop_exit)
        if self._landed_at_target_t < 0.0:
            self._landed_at_target_t = float(now)
        self._phase = "HARASS"

        local_ground = self._ground_enemies(bot=bot, pos=drop_pos, radius=11.0)
        if not self._ground_can_commit(bot=bot, troopers=[u for u in troopers if not bool(getattr(u, "is_loaded", False))], local_enemies=local_ground):
            if self._should_switch_target(mission_threat=mission_threat, threat_state=threat_state) and self._can_switch_target(now=now):
                self._recall_and_load(medivacs=medivacs, troopers=troopers, fallback=drop_exit)
                self._advance_target(now=now, reason="ground_intercepted")
                self._log_tick(now=now, reason="switch_after_intercept", medivacs=len(medivacs), troopers=len(troopers))
                return TaskResult.running("drop_switching_target")
            return self._retreat_home(bot=bot, medivacs=medivacs, troopers=troopers)

        self._harass_ground(bot=bot, troopers=troopers, target=drop_pos, regroup=target_base)
        if (float(now) - float(self._landed_at_target_t)) >= float(self.switch_target_after_s):
            workers_left = [e for e in local_ground if e.type_id in {U.SCV, U.PROBE, U.DRONE, U.MULE}]
            if (not workers_left or self._should_switch_target(mission_threat=mission_threat, threat_state=threat_state)) and self._can_switch_target(now=now):
                self._recall_and_load(medivacs=medivacs, troopers=troopers, fallback=drop_exit)
                self._advance_target(now=now, reason="next_exposed_base")
                self._log_tick(now=now, reason="cycling_target", medivacs=len(medivacs), troopers=len(troopers))
                return TaskResult.running("drop_cycling_target")

        self.awareness.mem.set(
            K("ops", "harass", "medivac_drop", "snapshot"),
            value={
                "target_idx": int(self._target_idx),
                "targets": [{"x": float(p.x), "y": float(p.y)} for p in self.target_locations],
                "medivacs": int(len(medivacs)),
                "troopers": int(len(troopers)),
                "phase": str(self._phase),
                "landed_at_target_t": float(round(self._landed_at_target_t, 2)) if self._landed_at_target_t >= 0.0 else None,
            },
            now=now,
            ttl=5.0,
        )
        self._active("medivac_drop_active")
        self._log_tick(now=now, reason="harassing", medivacs=len(medivacs), troopers=len(troopers))
        return TaskResult.running("medivac_drop_active")

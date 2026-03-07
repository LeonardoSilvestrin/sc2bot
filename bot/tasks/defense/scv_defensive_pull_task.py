from __future__ import annotations

from dataclasses import dataclass
import math

from ares.consts import UnitRole
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class ScvDefensivePullTask(BaseTask):
    base_tag: int
    base_pos: Point2
    threat_pos: Point2 | None = None
    log: DevLogger | None = None

    def __init__(
        self,
        *,
        base_tag: int,
        base_pos: Point2,
        threat_pos: Point2 | None = None,
        log: DevLogger | None = None,
    ) -> None:
        super().__init__(task_id="scv_defensive_pull", domain="DEFENSE", commitment=70)
        self.base_tag = int(base_tag)
        self.base_pos = base_pos
        self.threat_pos = threat_pos
        self.log = log

    def _resolve_base_pos(self, bot) -> Point2:
        th = bot.townhalls.find_by_tag(int(self.base_tag))
        if th is not None:
            return th.position
        return self.base_pos

    @staticmethod
    def _assign_role(bot, units: list, role: UnitRole) -> None:
        for unit in list(units or []):
            try:
                bot.mediator.assign_role(tag=int(unit.tag), role=role, remove_from_squad=True)
            except Exception:
                continue

    @staticmethod
    def _enemy_priority(unit) -> tuple[int, float]:
        tid = getattr(unit, "type_id", None)
        if tid in {U.PROBE, U.SCV, U.DRONE, U.PYLON, U.PHOTONCANNON}:
            return (4, float(getattr(unit, "health", 999.0) or 999.0))
        if tid in {U.ZEALOT, U.ZERGLING, U.MARINE, U.REAPER, U.ADEPT}:
            return (3, float(getattr(unit, "health", 999.0) or 999.0))
        if tid in {U.STALKER, U.ROACH, U.MARAUDER, U.HELLION}:
            return (2, float(getattr(unit, "health", 999.0) or 999.0))
        return (1, float(getattr(unit, "health", 999.0) or 999.0))

    @staticmethod
    def _hold_ring_point(*, base_pos: Point2, threat: Point2, tag: int) -> Point2:
        try:
            anchor = threat.towards(base_pos, 3.5) if threat != base_pos else base_pos
        except Exception:
            anchor = base_pos
        idx = int(tag) % 6
        angle = (2.0 * math.pi * float(idx)) / 6.0
        radius = 1.6 + (0.45 * float(idx % 2))
        return Point2((float(anchor.x) + (radius * math.cos(angle)), float(anchor.y) + (radius * math.sin(angle))))

    def _pick_target(self, *, scv, enemy_near, base_pos: Point2):
        scv_close = list(enemy_near.closer_than(4.5, scv.position))
        if scv_close:
            return min(
                scv_close,
                key=lambda e: (
                    -self._enemy_priority(e)[0],
                    float(scv.distance_to(e)),
                    self._enemy_priority(e)[1],
                ),
            )
        base_contact = []
        for enemy in list(enemy_near):
            try:
                if float(enemy.distance_to(base_pos)) <= 8.0:
                    base_contact.append(enemy)
            except Exception:
                continue
        if base_contact:
            return min(
                base_contact,
                key=lambda e: (
                    -self._enemy_priority(e)[0],
                    float(e.distance_to(base_pos)),
                    self._enemy_priority(e)[1],
                ),
            )
        return None

    @staticmethod
    def _repair_targets(bot, *, base_pos: Point2) -> list:
        allowed = {
            U.BUNKER,
            U.SIEGETANK,
            U.SIEGETANKSIEGED,
            U.COMMANDCENTER,
            U.ORBITALCOMMAND,
            U.PLANETARYFORTRESS,
            U.BARRACKS,
            U.BARRACKSREACTOR,
            U.BARRACKSTECHLAB,
            U.SUPPLYDEPOT,
            U.SUPPLYDEPOTLOWERED,
            U.FACTORY,
            U.FACTORYTECHLAB,
        }
        targets = []
        for unit in list(getattr(bot, "structures", []) or []) + list(getattr(bot, "units", []) or []):
            try:
                if getattr(unit, "type_id", None) not in allowed:
                    continue
                if float(unit.distance_to(base_pos)) > 12.0:
                    continue
                hp = float(getattr(unit, "health", 0.0) or 0.0)
                hp_max = float(getattr(unit, "health_max", 0.0) or 0.0)
                if hp_max <= 0.0 or hp >= hp_max:
                    continue
                targets.append(unit)
            except Exception:
                continue
        targets.sort(
            key=lambda u: (
                0 if getattr(u, "type_id", None) in {U.BUNKER, U.SIEGETANK, U.SIEGETANKSIEGED} else 1,
                float(getattr(u, "health_percentage", 1.0) or 1.0),
            )
        )
        return targets

    @staticmethod
    def _issue_repair(scv, target) -> bool:
        try:
            repair_fn = getattr(scv, "repair", None)
            if callable(repair_fn):
                repair_fn(target)
                return True
        except Exception:
            pass
        for ability_name in ("EFFECT_REPAIR_SCV", "EFFECT_REPAIR"):
            try:
                ability = getattr(AbilityId, ability_name, None)
                if ability is None:
                    continue
                scv(ability, target)
                return True
            except Exception:
                continue
        return False

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound(min_tags=1)
        if bound_err is not None:
            return bound_err

        units = [bot.units.find_by_tag(int(t)) for t in self.assigned_tags]
        units = [u for u in units if u is not None and u.type_id == U.SCV]
        if not units:
            return TaskResult.failed("no_scvs_alive")

        base_pos = self._resolve_base_pos(bot)
        threat = self.threat_pos or attention.combat.primary_threat_pos or base_pos
        enemy_near = bot.enemy_units.closer_than(16.0, base_pos)
        if enemy_near.amount <= 0:
            self._assign_role(bot, units, UnitRole.GATHERING)
            self._done("pull_no_enemy_near_base")
            return TaskResult.done("pull_no_enemy_near_base")

        self._assign_role(bot, units, UnitRole.REPAIRING)
        repair_targets = self._repair_targets(bot, base_pos=base_pos)
        issued = False
        for scv in units:
            hold = self._hold_ring_point(base_pos=base_pos, threat=threat, tag=int(getattr(scv, "tag", 0) or 0))
            target = self._pick_target(scv=scv, enemy_near=enemy_near, base_pos=base_pos)
            if target is not None:
                too_far_from_hold = False
                low_hp = False
                try:
                    too_far_from_hold = float(scv.distance_to(base_pos)) > 8.5 and float(scv.distance_to(target)) > 2.8
                except Exception:
                    too_far_from_hold = False
                try:
                    low_hp = float(getattr(scv, "health_percentage", 1.0) or 1.0) < 0.34
                except Exception:
                    low_hp = False
                if low_hp and float(scv.distance_to(target)) > 1.6:
                    scv.move(hold)
                    issued = True
                    continue
                if too_far_from_hold:
                    scv.move(hold)
                    issued = True
                    continue
                scv.attack(target)
                issued = True
                continue
            if repair_targets:
                top_repair = repair_targets[0]
                try:
                    if float(scv.distance_to(top_repair)) <= 3.0 or float(scv.distance_to(hold)) <= 4.0:
                        issued = self._issue_repair(scv, top_repair) or issued
                        if issued:
                            continue
                except Exception:
                    pass
            if float(scv.distance_to(hold)) > 1.5:
                scv.move(hold)
                issued = True
            elif repair_targets:
                issued = self._issue_repair(scv, repair_targets[0]) or issued

        if issued:
            self._active("scv_pull_active")
            return TaskResult.running("scv_pull_active")
        self._active("scv_pull_hold")
        return TaskResult.noop("scv_pull_hold")

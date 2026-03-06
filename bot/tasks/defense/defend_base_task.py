from __future__ import annotations

from dataclasses import dataclass
import math

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class DefendBaseTask(BaseTask):
    """
    Defesa de uma base (missão única por base).
    Internamente despacha micro por unidade/tipo.
    """

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
        super().__init__(task_id="defend_base", domain="DEFENSE", commitment=90)
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
    def _mineral_line_center(bot, base_pos: Point2) -> Point2:
        mfs = bot.mineral_field.closer_than(12.0, base_pos)
        if mfs.amount <= 0:
            return base_pos
        x = sum(float(m.position.x) for m in mfs) / float(mfs.amount)
        y = sum(float(m.position.y) for m in mfs) / float(mfs.amount)
        return Point2((x, y))

    def _highground_anchor(self, bot, *, base_pos: Point2, mineral_center: Point2) -> Point2:
        wall_hint = self._wall_hint(bot, base_pos=base_pos)
        points = [wall_hint, mineral_center]
        for r in (4.0, 6.0, 8.0):
            for i in range(16):
                ang = (2.0 * math.pi * float(i)) / 16.0
                p = Point2((float(wall_hint.x) + (r * math.cos(ang)), float(wall_hint.y) + (r * math.sin(ang))))
                if float(p.distance_to(base_pos)) <= 18.0:
                    points.append(p)

        def _pathable(p: Point2) -> bool:
            try:
                return bool(bot.in_pathing_grid(p))
            except Exception:
                return True

        def _height(p: Point2) -> float:
            if not _pathable(p):
                return -9999.0
            try:
                return float(bot.get_terrain_z_height(p))
            except Exception:
                return -9999.0

        fallback = wall_hint if _pathable(wall_hint) else (mineral_center if _pathable(mineral_center) else base_pos)
        best = fallback
        best_h = _height(best)
        for p in points:
            h = _height(p)
            if h > best_h:
                best = p
                best_h = h
        return best

    @staticmethod
    def _wall_structures_near_base(bot, *, base_pos: Point2) -> list:
        wall_types = {U.SUPPLYDEPOT, U.SUPPLYDEPOTLOWERED, U.BARRACKS, U.BARRACKSREACTOR, U.BARRACKSTECHLAB}
        out = []
        for s in list(getattr(bot, "structures", []) or []):
            try:
                if s.type_id in wall_types and float(s.distance_to(base_pos)) <= 20.0:
                    out.append(s)
            except Exception:
                continue
        return out

    def _wall_hint(self, bot, *, base_pos: Point2) -> Point2:
        wall_structs = self._wall_structures_near_base(bot, base_pos=base_pos)
        if wall_structs:
            x = sum(float(s.position.x) for s in wall_structs) / float(len(wall_structs))
            y = sum(float(s.position.y) for s in wall_structs) / float(len(wall_structs))
            return Point2((x, y))
        try:
            enemy_main = bot.enemy_start_locations[0]
            return base_pos.towards(enemy_main, 9.0)
        except Exception:
            return base_pos

    @staticmethod
    def _mine_slots(center: Point2) -> list[Point2]:
        out: list[Point2] = []
        for r in (4.5, 7.0):
            for i in range(4):
                ang = (2.0 * math.pi * float(i)) / 4.0
                out.append(Point2((float(center.x) + (r * math.cos(ang)), float(center.y) + (r * math.sin(ang)))))
        return out

    def _handle_tank(self, *, unit, anchor: Point2, threat: Point2, enemy_near) -> bool:
        if unit.type_id == U.SIEGETANKSIEGED:
            if float(unit.distance_to(anchor)) > 5.0 and int(enemy_near.amount) <= 0:
                unit(AbilityId.UNSIEGE_UNSIEGE)
                return True
            if int(enemy_near.amount) > 0:
                unit.attack(enemy_near.closest_to(unit))
                return True
            unit.attack(threat)
            return True

        if float(unit.distance_to(anchor)) > 2.5:
            unit.move(anchor)
            return True
        # Defensive posture by default: once in position, stay sieged.
        if unit.type_id == U.SIEGETANK:
            unit(AbilityId.SIEGEMODE_SIEGEMODE)
            return True
        if int(enemy_near.amount) > 0:
            unit.attack(enemy_near.closest_to(unit))
            return True
        return True

    def _handle_mine(self, *, unit, slot: Point2, threat: Point2, enemy_near_base) -> bool:
        if unit.type_id == U.WIDOWMINEBURROWED:
            if float(unit.distance_to(slot)) > 3.5 and int(enemy_near_base.amount) <= 0:
                unit(AbilityId.BURROWUP_WIDOWMINE)
                return True
            return False

        if float(unit.distance_to(slot)) > 1.8:
            unit.move(slot)
            return True
        if int(enemy_near_base.amount) > 0 or float(unit.distance_to(threat)) <= 14.0:
            unit(AbilityId.BURROWDOWN_WIDOWMINE)
            return True
        unit.move(slot)
        return True

    @staticmethod
    def _handle_general(*, unit, base_pos: Point2, threat: Point2, enemy_near_base, now: float) -> bool:
        if unit.type_id == U.MEDIVAC:
            follow = threat.towards(base_pos, 6.0)
            unit.move(follow)
            return True
        if int(enemy_near_base.amount) > 0:
            unit.attack(enemy_near_base.closest_to(unit))
            return True
        # Keep units active on-map even in calm windows.
        phase = int(float(now) // 4.0)
        sign = 1.0 if ((int(getattr(unit, "tag", 0) or 0) + phase) % 2 == 0) else -1.0
        patrol = Point2((float(base_pos.x) + (6.0 * sign), float(base_pos.y) + (3.5 * sign)))
        unit.move(patrol)
        return True

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound(min_tags=1)
        if bound_err is not None:
            return bound_err

        units = [bot.units.find_by_tag(int(t)) for t in self.assigned_tags]
        units = [u for u in units if u is not None]
        if not units:
            return TaskResult.failed("no_defenders_alive")

        base_pos = self._resolve_base_pos(bot)
        mineral_center = self._mineral_line_center(bot, base_pos)
        tank_anchor = self._highground_anchor(bot, base_pos=base_pos, mineral_center=mineral_center)
        mine_slots = self._mine_slots(mineral_center)
        threat = self.threat_pos or attention.combat.primary_threat_pos or base_pos
        enemy_near_base = bot.enemy_units.closer_than(22.0, base_pos)

        issued = False
        mine_idx = 0
        for u in units:
            if u.type_id in {U.SIEGETANK, U.SIEGETANKSIEGED}:
                enemy_near = bot.enemy_units.closer_than(13.0, u.position)
                issued = self._handle_tank(unit=u, anchor=tank_anchor, threat=threat, enemy_near=enemy_near) or issued
                continue
            if u.type_id in {U.WIDOWMINE, U.WIDOWMINEBURROWED}:
                slot = mine_slots[mine_idx % len(mine_slots)] if mine_slots else mineral_center
                mine_idx += 1
                issued = self._handle_mine(unit=u, slot=slot, threat=threat, enemy_near_base=enemy_near_base) or issued
                continue
            issued = self._handle_general(
                unit=u,
                base_pos=base_pos,
                threat=threat,
                enemy_near_base=enemy_near_base,
                now=float(tick.time),
            ) or issued

        if issued:
            self._active("defend_base_active")
            return TaskResult.running("defend_base_active")
        self._active("defend_base_hold")
        return TaskResult.noop("defend_base_hold")

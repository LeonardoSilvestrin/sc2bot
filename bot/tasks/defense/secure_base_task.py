from __future__ import annotations

from dataclasses import dataclass
import math

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick

_NON_COMBAT = {U.SCV, U.PROBE, U.DRONE, U.MULE, U.LARVA, U.EGG}


@dataclass
class SecureBaseTask(BaseTask):
    awareness: Awareness
    base_pos: Point2
    staging_pos: Point2
    hold_pos: Point2
    label: str = "our_nat"
    log: DevLogger | None = None

    def __init__(
        self,
        *,
        awareness: Awareness,
        base_pos: Point2,
        staging_pos: Point2,
        hold_pos: Point2,
        label: str = "our_nat",
        log: DevLogger | None = None,
    ) -> None:
        super().__init__(task_id="secure_base", domain="MAP_CONTROL", commitment=72)
        self.awareness = awareness
        self.base_pos = base_pos
        self.staging_pos = staging_pos
        self.hold_pos = hold_pos
        self.label = str(label)
        self.log = log

    @staticmethod
    def _enemy_combat_near(bot, *, center: Point2, radius: float) -> list:
        out = []
        for unit in list(getattr(bot, "enemy_units", []) or []):
            try:
                if unit.type_id in _NON_COMBAT:
                    continue
                if float(unit.distance_to(center)) <= float(radius):
                    out.append(unit)
            except Exception:
                continue
        for struct in list(getattr(bot, "enemy_structures", []) or []):
            try:
                if float(struct.distance_to(center)) > float(radius):
                    continue
                if struct.type_id in {
                    U.COMMANDCENTER,
                    U.ORBITALCOMMAND,
                    U.PLANETARYFORTRESS,
                    U.HATCHERY,
                    U.LAIR,
                    U.HIVE,
                    U.NEXUS,
                }:
                    continue
                out.append(struct)
            except Exception:
                continue
        return out

    @staticmethod
    def _slots(center: Point2, *, radius: float, count: int) -> list[Point2]:
        out: list[Point2] = []
        for idx in range(max(1, int(count))):
            ang = (2.0 * math.pi * float(idx)) / float(max(1, int(count)))
            out.append(
                Point2(
                    (
                        float(center.x) + (float(radius) * math.cos(ang)),
                        float(center.y) + (float(radius) * math.sin(ang)),
                    )
                )
            )
        return out

    @staticmethod
    def _point_from_payload(payload, *, fallback: Point2) -> Point2:
        if not isinstance(payload, dict):
            return fallback
        try:
            return Point2((float(payload.get("x", fallback.x)), float(payload.get("y", fallback.y))))
        except Exception:
            return fallback

    def _snapshot(self, *, now: float) -> dict:
        snap = self.awareness.mem.get(
            K("intel", "map_control", "our_nat", "snapshot"),
            now=now,
            default={},
        ) or {}
        return snap if isinstance(snap, dict) else {}

    def _should_release(self, *, bot, now: float, enemy_near: list, enemy_main: list) -> bool:
        snap = self._snapshot(now=now)
        if enemy_main:
            return True
        if enemy_near:
            return False
        should_secure = bool(snap.get("should_secure", False))
        rush_state = str(self.awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        nat_taken = False
        for th in list(getattr(bot, "townhalls", []) or []):
            try:
                if float(th.distance_to(self.base_pos)) <= 8.0:
                    nat_taken = True
                    break
            except Exception:
                continue
        return bool((not should_secure) or (nat_taken and rush_state not in {"SUSPECTED", "CONFIRMED", "HOLDING"}))

    def _handle_tank(self, *, unit, anchor: Point2, enemy_near: list) -> bool:
        if unit.type_id == U.SIEGETANKSIEGED:
            if enemy_near:
                unit.attack(min(enemy_near, key=lambda e: float(unit.distance_to(e))))
                return True
            if float(unit.distance_to(anchor)) > 5.0:
                unit(AbilityId.UNSIEGE_UNSIEGE)
                return True
            return True
        if float(unit.distance_to(anchor)) > 2.5:
            unit.move(anchor)
            return True
        unit(AbilityId.SIEGEMODE_SIEGEMODE)
        return True

    def _handle_mine(self, *, unit, slot: Point2, enemy_near: list) -> bool:
        if unit.type_id == U.WIDOWMINEBURROWED:
            if enemy_near:
                return False
            if float(unit.distance_to(slot)) > 3.0:
                unit(AbilityId.BURROWUP_WIDOWMINE)
                return True
            return False
        if float(unit.distance_to(slot)) > 1.7:
            unit.move(slot)
            return True
        unit(AbilityId.BURROWDOWN_WIDOWMINE)
        return True

    def _handle_general(self, *, unit, slot: Point2, enemy_near: list) -> bool:
        if unit.type_id == U.MEDIVAC:
            unit.move(self.staging_pos)
            return True
        if enemy_near:
            unit.attack(min(enemy_near, key=lambda e: float(unit.distance_to(e))))
            return True
        if float(unit.distance_to(slot)) > 2.0:
            unit.move(slot)
            return True
        unit.attack(self.hold_pos)
        return True

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound(min_tags=1)
        if bound_err is not None:
            return bound_err

        now = float(tick.time)
        snap = self._snapshot(now=now)
        self.base_pos = self._point_from_payload(snap.get("target"), fallback=self.base_pos)
        self.staging_pos = self._point_from_payload(snap.get("staging"), fallback=self.staging_pos)
        self.hold_pos = self._point_from_payload(snap.get("hold"), fallback=self.hold_pos)

        units = [bot.units.find_by_tag(int(tag)) for tag in self.assigned_tags]
        units = [u for u in units if u is not None]
        if not units:
            return TaskResult.failed("no_units_alive")

        enemy_near = self._enemy_combat_near(bot, center=self.hold_pos, radius=18.0)
        enemy_main = self._enemy_combat_near(bot, center=bot.start_location, radius=18.0)
        if self._should_release(bot=bot, now=now, enemy_near=enemy_near, enemy_main=enemy_main):
            self._done("secure_base_released")
            return TaskResult.done("secure_base_released")

        perimeter = self._slots(self.hold_pos, radius=4.5, count=max(4, len(units)))
        mine_slots = self._slots(self.base_pos, radius=3.5, count=4)
        issued = False
        mine_idx = 0
        general_idx = 0

        for unit in units:
            if unit.type_id in {U.SIEGETANK, U.SIEGETANKSIEGED}:
                issued = self._handle_tank(unit=unit, anchor=self.hold_pos, enemy_near=enemy_near) or issued
                continue
            if unit.type_id in {U.WIDOWMINE, U.WIDOWMINEBURROWED}:
                slot = mine_slots[mine_idx % len(mine_slots)] if mine_slots else self.base_pos
                mine_idx += 1
                issued = self._handle_mine(unit=unit, slot=slot, enemy_near=enemy_near) or issued
                continue
            slot = perimeter[general_idx % len(perimeter)] if perimeter else self.staging_pos
            general_idx += 1
            issued = self._handle_general(unit=unit, slot=slot, enemy_near=enemy_near) or issued

        if issued:
            self._active("securing_base")
            return TaskResult.running("securing_base")
        return TaskResult.noop("secure_base_idle")

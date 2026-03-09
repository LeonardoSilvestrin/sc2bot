"""
HoldAnchorTask: posture task for the army bulk.

Responsibility: move the army bulk to the current posture anchor and hold it there.
This task executes posture; it does not derive posture.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.intel.strategy.i3_army_posture_intel import ArmyPosture
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick

_BULK_TYPES = {
    U.MARINE,
    U.MARAUDER,
    U.REAPER,
    U.HELLION,
    U.CYCLONE,
    U.SIEGETANK,
    U.SIEGETANKSIEGED,
    U.THOR,
    U.THORAP,
    U.MEDIVAC,
    U.WIDOWMINE,
    U.WIDOWMINEBURROWED,
}

# Units that need extra care instead of blindly rushing the anchor.
_SLOW_POSITIONAL = {U.SIEGETANK, U.SIEGETANKSIEGED, U.WIDOWMINE, U.WIDOWMINEBURROWED}

# Raio dentro do qual consideramos a unidade "no anchor"
_AT_ANCHOR_RADIUS = 4.5
_SLOW_AT_ANCHOR_RADIUS = 7.0
# Raio a partir do qual tanks sieged recebem unsiege para se mover ao novo anchor.
# Mantemos histerese maior para evitar "senta/levanta" com anchors oscilando poucos tiles.
_TANK_UNSIEGE_TO_MOVE_RADIUS = 12.0
_TANK_LOCAL_HOLD_RADIUS = 15.0


def _point_from_payload(payload) -> Point2 | None:
    if not isinstance(payload, dict):
        return None
    try:
        return Point2((float(payload.get("x", 0.0) or 0.0), float(payload.get("y", 0.0) or 0.0)))
    except Exception:
        return None


def _nat_landing_reservation(awareness: Awareness, *, now: float) -> tuple[Point2 | None, Point2 | None]:
    snap = awareness.mem.get(K("intel", "map_control", "our_nat", "snapshot"), now=now, default={}) or {}
    if not isinstance(snap, dict):
        return None, None
    if not bool(snap.get("nat_offsite", False) or snap.get("safe_to_land", False)):
        return None, None
    return _point_from_payload(snap.get("target")), _point_from_payload(snap.get("staging"))


@dataclass
class HoldAnchorTask(BaseTask):
    """
    Hold the current operational posture anchor.
    The anchor is read from awareness each tick and is not fixed at creation time.
    """

    awareness: Awareness
    log: DevLogger | None = None
    log_every_iters: int = 15
    _iters: int = field(default=0, init=False, repr=False)

    def __init__(self, *, awareness: Awareness, log: DevLogger | None = None, log_every_iters: int = 15):
        super().__init__(task_id="hold_anchor", domain="MAP_CONTROL", commitment=86)
        self.awareness = awareness
        self.log = log
        self.log_every_iters = int(log_every_iters)
        self._iters = 0

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        self._iters += 1
        now = float(tick.time)

        guard = self.require_mission_bound(min_tags=1)
        if guard is not None:
            return guard

        posture_snap = self.awareness.mem.get(K("strategy", "army", "snapshot"), now=now, default={}) or {}
        if not isinstance(posture_snap, dict):
            posture_snap = {}

        anchor = _point_from_payload(posture_snap.get("anchor"))
        posture_str = str(posture_snap.get("posture", "HOLD_MAIN_RAMP") or "HOLD_MAIN_RAMP")
        nat_landing_target, nat_landing_fallback = _nat_landing_reservation(self.awareness, now=now)

        if anchor is None:
            return TaskResult.noop("no_anchor_defined")

        assigned_set = set(int(t) for t in self.assigned_tags)
        bulk = bot.units.filter(lambda u: int(u.tag) in assigned_set)

        if bulk.amount == 0:
            return TaskResult.failed("assigned_units_gone")

        medivacs = bulk.of_type({U.MEDIVAC})
        mobile = bulk - medivacs
        slow = mobile.of_type(_SLOW_POSITIONAL)
        fast = mobile - slow

        issued = 0

        for unit in fast:
            try:
                if nat_landing_target is not None and float(unit.distance_to(nat_landing_target)) <= 4.75:
                    retreat = nat_landing_fallback or anchor
                    if float(unit.distance_to(retreat)) > 1.5:
                        unit.move(retreat)
                    else:
                        unit.attack(retreat)
                    issued += 1
                    continue

                dist = float(unit.distance_to(anchor))
                if dist > float(_AT_ANCHOR_RADIUS):
                    unit.move(anchor)
                    issued += 1
                elif not bool(getattr(unit, "is_attacking", False)):
                    unit.attack(anchor)
                    issued += 1
            except Exception:
                continue

        for unit in slow:
            try:
                if nat_landing_target is not None and float(unit.distance_to(nat_landing_target)) <= 4.9:
                    if unit.type_id == U.SIEGETANKSIEGED:
                        unit(AbilityId.UNSIEGE_UNSIEGE)
                        issued += 1
                        continue
                    if unit.type_id == U.WIDOWMINEBURROWED:
                        unit(AbilityId.BURROWUP_WIDOWMINE)
                        issued += 1
                        continue
                    retreat = nat_landing_fallback or anchor
                    if float(unit.distance_to(retreat)) > 1.5:
                        unit.move(retreat)
                        issued += 1
                    continue

                dist = float(unit.distance_to(anchor))
                is_sieged = unit.type_id == U.SIEGETANKSIEGED

                if is_sieged:
                    enemy_near = bot.enemy_units.closer_than(_TANK_LOCAL_HOLD_RADIUS, unit)
                    if dist > float(_TANK_UNSIEGE_TO_MOVE_RADIUS) and int(enemy_near.amount) <= 0:
                        unit(AbilityId.UNSIEGE_UNSIEGE)
                        issued += 1
                    continue

                if dist > float(_SLOW_AT_ANCHOR_RADIUS):
                    unit.move(anchor)
                    issued += 1
                    continue

                if unit.type_id == U.SIEGETANK and posture_str in {
                    ArmyPosture.HOLD_NAT_CHOKE.value,
                    ArmyPosture.SECURE_NAT.value,
                    ArmyPosture.CONTROLLED_RETAKE.value,
                }:
                    enemy_too_close = bot.enemy_units.closer_than(4.0, unit)
                    if int(enemy_too_close.amount) <= 0:
                        unit(AbilityId.SIEGEMODE_SIEGEMODE)
                        issued += 1
            except Exception:
                continue

        if medivacs.amount > 0 and fast.amount > 0:
            try:
                follow_target = fast.center
                for med in medivacs:
                    med.move(follow_target)
                    issued += 1
            except Exception:
                pass

        if self._iters % self.log_every_iters == 0 and self.log is not None:
            self.log.emit(
                "hold_anchor_tick",
                {
                    "posture": posture_str,
                    "anchor": {"x": float(anchor.x), "y": float(anchor.y)},
                    "bulk_count": int(bulk.amount),
                    "issued_commands": int(issued),
                },
                meta={"module": "task", "component": "hold_anchor_task"},
            )

        return TaskResult.running("holding_anchor")

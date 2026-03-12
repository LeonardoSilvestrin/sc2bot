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

_MINE_SLOT_ROLES = {"mine_choke", "mine_flank_left", "mine_flank_right"}


@dataclass
class WidowmineLurkTask(BaseTask):
    awareness: Awareness
    log: DevLogger | None = None
    home_slot_radius: float = 1.6
    home_reposition_radius: float = 3.6
    drop_arrival_radius: float = 7.5
    drop_abort_urgency: int = 16
    group_size: int = 2

    def __init__(self, *, awareness: Awareness, log: DevLogger | None = None) -> None:
        super().__init__(task_id="widowmine_lurk", domain="DEFENSE", commitment=24)
        self.awareness = awareness
        self.log = log
        self._home_slot_by_tag: dict[int, int] = {}

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
    def _enemy_main(bot) -> Point2:
        return bot.enemy_start_locations[0]

    def _enemy_natural(self, bot) -> Point2:
        enemy_main = self._enemy_main(bot)
        exps = list(getattr(bot, "expansion_locations_list", []) or [])
        exps = [p for p in exps if float(p.distance_to(enemy_main)) > 5.0]
        if not exps:
            return enemy_main
        exps.sort(key=lambda p: float(p.distance_to(enemy_main)))
        return exps[0]

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
    def _townhalls_sorted(bot) -> list:
        ths = [th for th in list(getattr(bot, "townhalls", []) or []) if bool(getattr(th, "is_ready", False))]
        try:
            ths.sort(key=lambda th: float(th.distance_to(bot.start_location)))
        except Exception:
            pass
        return ths

    @staticmethod
    def _point_from_payload(payload) -> Point2 | None:
        if not isinstance(payload, dict):
            return None
        try:
            return Point2((float(payload.get("x", 0.0) or 0.0), float(payload.get("y", 0.0) or 0.0)))
        except Exception:
            return None

    def _territory_zone_slots(self, *, now: float, zone_key: str) -> list[Point2]:
        snap = self.awareness.mem.get(K("intel", "territory", "defense", "snapshot"), now=now, default={}) or {}
        if not isinstance(snap, dict):
            return []
        zones = snap.get("zones", {})
        if not isinstance(zones, dict):
            return []
        zone = zones.get(str(zone_key), {})
        if not isinstance(zone, dict):
            return []
        out: list[Point2] = []
        for slot in list(zone.get("active_slots", []) or []):
            if not isinstance(slot, dict):
                continue
            if str(slot.get("role", "") or "") not in _MINE_SLOT_ROLES:
                continue
            pos = self._point_from_payload(slot.get("position"))
            if pos is not None:
                out.append(pos)
        return out

    def _territorial_home_slots(self, bot, *, now: float) -> list[Point2]:
        snap = self.awareness.mem.get(K("intel", "territory", "defense", "snapshot"), now=now, default={}) or {}
        if not isinstance(snap, dict):
            return []
        zones = snap.get("zones", {})
        if not isinstance(zones, dict):
            return []
        enemy_main = self._enemy_main(bot)
        zone_entries: list[tuple[float, str, list[Point2]]] = []
        for zone_key in ("main_ramp", "natural_front", "third_front"):
            slots = self._territory_zone_slots(now=now, zone_key=zone_key)
            if not slots:
                continue
            zone = zones.get(zone_key, {})
            center = self._point_from_payload(zone.get("center")) if isinstance(zone, dict) else None
            ref = center or slots[0]
            try:
                enemy_dist = float(ref.distance_to(enemy_main))
            except Exception:
                enemy_dist = 9999.0
            zone_entries.append((enemy_dist, str(zone_key), slots))
        if not zone_entries:
            return []
        zone_entries.sort(key=lambda item: item[0])
        out: list[Point2] = []
        for idx, (_enemy_dist, zone_key, slots) in enumerate(zone_entries):
            copies = 2 if idx == 0 else 1
            if zone_key == "natural_front":
                copies = max(copies, 1)
            for slot in slots:
                out.append(slot)
                if copies <= 1:
                    continue
                out.extend(self._slots(slot, radius=1.1, count=max(1, copies - 1)))
        return out

    def _home_groups(self, bot) -> list[dict]:
        enemy_main = self._enemy_main(bot)
        ths = self._townhalls_sorted(bot)
        main = ths[0].position if ths else bot.start_location
        try:
            nat = bot.mediator.get_own_nat
        except Exception:
            nat = main.towards(enemy_main, 8.0)
        groups: list[dict] = [
            {"name": "nat_front", "center": nat.towards(enemy_main, 5.5), "count": 2},
            {"name": "main_nat_lane", "center": main.towards(nat, 7.0), "count": 2},
        ]
        if len(ths) >= 3:
            third = ths[2].position
            between = Point2(((float(nat.x) + float(third.x)) / 2.0, (float(nat.y) + float(third.y)) / 2.0))
            groups.append({"name": "nat_third_lane", "center": between, "count": 2})
            groups.append({"name": "third_front", "center": third.towards(enemy_main, 5.0), "count": 2})
        elif len(ths) >= 2:
            groups.append({"name": "nat_back", "center": nat.towards(main, 4.0), "count": 2})
        return groups

    def _drop_enabled(self, *, bot, attention: Attention, medivac, mines: list) -> bool:
        if medivac is None or len(mines) < 2:
            return False
        if int(attention.combat.primary_urgency) >= int(self.drop_abort_urgency):
            return False
        rush_state = str(self.awareness.mem.get(K("enemy", "rush", "state"), now=float(attention.time), default="NONE") or "NONE").upper()
        if rush_state in {"CONFIRMED", "HOLDING"}:
            return False
        return True

    def _handle_home_mine(self, *, bot, mine, slot: Point2) -> bool:
        enemy_near = bot.enemy_units.closer_than(7.0, slot)
        if mine.type_id == U.WIDOWMINEBURROWED:
            if float(mine.distance_to(slot)) > float(self.home_reposition_radius) and int(enemy_near.amount) <= 0:
                mine(AbilityId.BURROWUP_WIDOWMINE)
                return True
            return False
        if float(mine.distance_to(slot)) > float(self.home_slot_radius):
            mine.move(slot)
            return True
        if int(enemy_near.amount) <= 1:
            mine(AbilityId.BURROWDOWN_WIDOWMINE)
            return True
        return False

    def _handle_drop_group(self, *, bot, medivac, mines: list, target: Point2, retreat: Point2) -> bool:
        issued = False
        if medivac is None or len(mines) < 2:
            return issued
        loadable = [m for m in mines if m.type_id == U.WIDOWMINE]
        burrowed = [m for m in mines if m.type_id == U.WIDOWMINEBURROWED]
        for mine in burrowed:
            mine(AbilityId.BURROWUP_WIDOWMINE)
            issued = True
        cargo_used = int(getattr(medivac, "cargo_used", 0) or 0)
        if cargo_used < 4 and loadable:
            for mine in loadable:
                if float(mine.distance_to(medivac)) <= 3.0:
                    mine(AbilityId.SMART, medivac)
                else:
                    mine.move(medivac.position)
                issued = True
            if not issued:
                medivac.move(loadable[0].position)
                issued = True
            return issued
        if float(medivac.distance_to(target)) > float(self.drop_arrival_radius):
            medivac.move(target)
            return True
        medivac(AbilityId.UNLOADALLAT_MEDIVAC, target)
        issued = True
        drop_slots = self._slots(target, radius=2.2, count=max(2, len(mines)))
        for idx, mine in enumerate(mines):
            slot = drop_slots[idx % len(drop_slots)]
            if mine.type_id == U.WIDOWMINEBURROWED:
                if float(mine.distance_to(slot)) > 2.6:
                    mine(AbilityId.BURROWUP_WIDOWMINE)
                    issued = True
                continue
            if float(mine.distance_to(slot)) > 1.4:
                mine.move(slot)
                issued = True
            else:
                mine(AbilityId.BURROWDOWN_WIDOWMINE)
                issued = True
        if float(medivac.distance_to(retreat)) > 5.0:
            medivac.move(retreat)
            issued = True
        return issued

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound(min_tags=1)
        if bound_err is not None:
            return bound_err

        units = [bot.units.find_by_tag(int(t)) for t in self.assigned_tags]
        units = [u for u in units if u is not None]
        mines = [u for u in units if u.type_id in {U.WIDOWMINE, U.WIDOWMINEBURROWED}]
        mines.sort(key=lambda u: int(getattr(u, "tag", 0) or 0))
        medivacs = [u for u in units if u.type_id == U.MEDIVAC]
        if not mines:
            return TaskResult.failed("no_widowmines_alive")

        medivac = medivacs[0] if medivacs else None
        home_groups = self._home_groups(bot)
        drop_target = self._mineral_line_center(bot, self._enemy_natural(bot))
        drop_retreat = self._enemy_natural(bot).towards(self._enemy_main(bot), 8.0)

        drop_enabled = self._drop_enabled(bot=bot, attention=attention, medivac=medivac, mines=mines)
        static_mines = list(mines)
        drop_mines: list = []
        if drop_enabled and len(static_mines) >= 2:
            drop_mines = static_mines[-2:]
            static_mines = static_mines[:-2]

        issued = False
        if drop_enabled and medivac is not None:
            issued = self._handle_drop_group(bot=bot, medivac=medivac, mines=drop_mines, target=drop_target, retreat=drop_retreat) or issued

        slot_idx = 0
        home_slots: list[Point2] = self._territorial_home_slots(bot, now=float(tick.time))
        if not home_slots:
            for group in home_groups:
                count = max(1, int(group.get("count", self.group_size)))
                home_slots.extend(self._slots(group["center"], radius=2.1, count=count))
        if not home_slots:
            home_slots = [bot.start_location]
        alive_tags = {int(getattr(mine, "tag", 0) or 0) for mine in static_mines}
        self._home_slot_by_tag = {
            tag: idx for tag, idx in self._home_slot_by_tag.items() if tag in alive_tags and 0 <= int(idx) < len(home_slots)
        }
        next_slot_idx = 0
        for mine in static_mines:
            tag = int(getattr(mine, "tag", 0) or 0)
            assigned_idx = self._home_slot_by_tag.get(tag)
            if assigned_idx is None:
                assigned_idx = int(next_slot_idx % len(home_slots))
                self._home_slot_by_tag[tag] = assigned_idx
                next_slot_idx += 1
            slot = home_slots[int(assigned_idx) % len(home_slots)]
            slot_idx += 1
            issued = self._handle_home_mine(bot=bot, mine=mine, slot=slot) or issued

        now = float(tick.time)
        self.awareness.mem.set(
            K("ops", "widowmine", "lurk", "snapshot"),
            value={
                "assigned_mines": int(len(mines)),
                "home_mines": int(len(static_mines)),
                "drop_mines": int(len(drop_mines)),
                "drop_enabled": bool(drop_enabled),
                "has_medivac": bool(medivac is not None),
            },
            now=now,
            ttl=5.0,
        )
        self._active("widowmine_lurk_active")
        return TaskResult.running("widowmine_lurk_active" if issued else "widowmine_lurk_hold")

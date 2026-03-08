from __future__ import annotations

from dataclasses import dataclass
import math

from ares.consts import BuildingSize
from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class DefenseBunkerTask(BaseTask):
    base_tag: int
    base_pos: Point2
    threat_pos: Point2 | None = None
    anchor_mode: str = "BASE"
    awareness: Awareness | None = None
    log: DevLogger | None = None
    _target_pos: Point2 | None = None
    _next_issue_at: float = 0.0
    _issue_attempts: int = 0
    _blocked_positions: list[Point2] | None = None

    def __init__(
        self,
        *,
        awareness: Awareness | None = None,
        base_tag: int,
        base_pos: Point2,
        threat_pos: Point2 | None = None,
        anchor_mode: str = "BASE",
        log: DevLogger | None = None,
    ) -> None:
        super().__init__(task_id="defense_bunker", domain="DEFENSE", commitment=70)
        self.awareness = awareness
        self.base_tag = int(base_tag)
        self.base_pos = base_pos
        self.threat_pos = threat_pos
        self.anchor_mode = str(anchor_mode or "BASE").upper()
        self.log = log
        self._target_pos = None
        self._next_issue_at = 0.0
        self._issue_attempts = 0
        self._blocked_positions = []

    def _resolve_base_pos(self, bot) -> Point2:
        th = bot.townhalls.find_by_tag(int(self.base_tag))
        if th is not None:
            return th.position
        return self.base_pos

    @staticmethod
    def _release_worker(bot, worker) -> None:
        try:
            bot.mediator.assign_role(tag=int(worker.tag), role=UnitRole.GATHERING, remove_from_squad=True)
        except Exception:
            pass

    def _bunker_anchor(self, bot, *, base_pos: Point2) -> Point2:
        mode = str(self.anchor_mode or "BASE").upper()
        if mode == "MAIN_RAMP":
            try:
                ramp = getattr(bot, "main_base_ramp", None)
                if ramp is not None:
                    barracks_pos = getattr(ramp, "barracks_correct_placement", None)
                    if barracks_pos is not None:
                        return barracks_pos
                    top = getattr(ramp, "top_center", None)
                    if top is not None:
                        return top
            except Exception:
                pass
            try:
                enemy_main = bot.enemy_start_locations[0]
                return bot.start_location.towards(enemy_main, 8.0)
            except Exception:
                return bot.start_location
        if mode == "NAT_CHOKE":
            try:
                enemy_main = bot.enemy_start_locations[0]
                return base_pos.towards(enemy_main, 4.5)
            except Exception:
                return base_pos
        if mode == "PERIMETER":
            try:
                if self.threat_pos is not None:
                    return base_pos.towards(self.threat_pos, 5.0)
            except Exception:
                pass
        try:
            main_anchor = bot.start_location
        except Exception:
            main_anchor = None
        if main_anchor is None:
            return base_pos
        try:
            return base_pos.towards(main_anchor, 4.5)
        except Exception:
            return base_pos

    @staticmethod
    def _ramp_reference_points(bot) -> tuple[Point2 | None, Point2 | None, Point2 | None]:
        try:
            ramp = getattr(bot, "main_base_ramp", None)
            top = getattr(ramp, "top_center", None) if ramp is not None else None
            barracks_pos = getattr(ramp, "barracks_correct_placement", None) if ramp is not None else None
            bottom = getattr(ramp, "bottom_center", None) if ramp is not None else None
            return top, barracks_pos, bottom
        except Exception:
            return None, None, None

    @staticmethod
    def _placements_dict(bot) -> dict:
        try:
            return dict(bot.mediator.get_placements_dict or {})
        except Exception:
            return {}

    @staticmethod
    def _height(bot, pos: Point2 | None) -> float:
        if pos is None:
            return -9999.0
        try:
            return float(bot.get_terrain_z_height(pos))
        except Exception:
            try:
                return float(bot.get_terrain_height(pos))
            except Exception:
                return -9999.0

    def _ramp_edge_depth(self, bot, *, pos: Point2, bottom: Point2 | None, lowground_h: float) -> float:
        if bottom is None:
            return 9999.0
        for dist in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0):
            try:
                probe = pos.towards(bottom, dist)
            except Exception:
                continue
            probe_h = self._height(bot, probe)
            if probe_h <= (float(lowground_h) + 0.25):
                return float(dist)
        return 9999.0

    def _main_wall_bunker_slots(self, bot) -> list[Point2]:
        top, _barracks_pos, bottom = self._ramp_reference_points(bot)
        start = getattr(bot, "start_location", None)
        lowground_h = self._height(bot, bottom)
        highground_h = max(self._height(bot, top), self._height(bot, start))
        try:
            base_location = bot.start_location
        except Exception:
            base_location = None
        placements = self._placements_dict(bot)
        if base_location is None or base_location not in placements:
            return []
        per_size = placements[base_location].get(BuildingSize.THREE_BY_THREE, {}) or {}
        out: list[Point2] = []
        for pos, info in per_size.items():
            if not isinstance(info, dict):
                continue
            if not bool(info.get("is_wall", False)):
                continue
            if not bool(info.get("bunker", False)):
                continue
            try:
                pos_h = self._height(bot, pos)
                if pos_h <= (float(lowground_h) + 0.25):
                    continue
                if highground_h > -9990.0 and pos_h < (float(highground_h) - 0.75):
                    continue
                edge_depth = self._ramp_edge_depth(bot, pos=pos, bottom=bottom, lowground_h=lowground_h)
                if edge_depth > 4.25:
                    continue
                if bottom is not None and float(pos.distance_to(bottom)) > 6.5:
                    continue
                if top is not None and float(pos.distance_to(top)) > 6.5:
                    continue
                if start is not None and top is not None and float(pos.distance_to(start)) < (float(top.distance_to(start)) - 0.75):
                    continue
            except Exception:
                pass
            out.append(pos)
        return out

    def _is_exact_main_wall_bunker_slot(self, bot, *, pos: Point2) -> bool:
        for slot in self._main_wall_bunker_slots(bot):
            try:
                if float(slot.distance_to(pos)) <= 0.75:
                    return True
            except Exception:
                continue
        return False

    def _main_ramp_probe_targets(self, bot, *, anchor: Point2) -> list[Point2]:
        top, barracks_pos, bottom = self._ramp_reference_points(bot)
        start = getattr(bot, "start_location", None)
        targets: list[Point2] = []
        for slot in self._main_wall_bunker_slots(bot):
            targets.append(slot)
            if start is not None:
                try:
                    targets.append(slot.towards(start, 1.5))
                    targets.append(slot.towards(start, 2.5))
                except Exception:
                    pass
        for point in (top, barracks_pos, bottom, anchor):
            if point is None:
                continue
            duplicate = False
            for existing in targets:
                try:
                    if float(existing.distance_to(point)) <= 0.75:
                        duplicate = True
                        break
                except Exception:
                    continue
            if not duplicate:
                targets.append(point)
        if top is not None and bottom is not None:
            try:
                targets.append(top.towards(bottom, 1.5))
                targets.append(top.towards(bottom, 2.5))
            except Exception:
                pass
        if barracks_pos is not None and bottom is not None:
            try:
                targets.append(barracks_pos.towards(bottom, 1.5))
            except Exception:
                pass
        return targets

    def _main_ramp_highground_targets(self, bot, *, anchor: Point2) -> list[Point2]:
        top, barracks_pos, bottom = self._ramp_reference_points(bot)
        start = getattr(bot, "start_location", None)
        out: list[Point2] = []
        candidates = [anchor, top, barracks_pos]
        for center in candidates:
            if center is None:
                continue
            for point in (center,):
                duplicate = False
                for existing in out:
                    try:
                        if float(existing.distance_to(point)) <= 0.75:
                            duplicate = True
                            break
                    except Exception:
                        continue
                if not duplicate:
                    out.append(point)
            if start is not None:
                for dist in (0.75, 1.5, 2.25, 3.0):
                    try:
                        point = center.towards(start, dist)
                    except Exception:
                        continue
                    duplicate = False
                    for existing in out:
                        try:
                            if float(existing.distance_to(point)) <= 0.75:
                                duplicate = True
                                break
                        except Exception:
                            continue
                    if not duplicate:
                        out.append(point)
            if bottom is not None:
                for dist in (0.75, 1.5):
                    try:
                        point = center.towards(bottom, dist)
                    except Exception:
                        continue
                    duplicate = False
                    for existing in out:
                        try:
                            if float(existing.distance_to(point)) <= 0.75:
                                duplicate = True
                                break
                        except Exception:
                            continue
                    if not duplicate:
                        out.append(point)
        return out

    def _main_wall_fallback_targets(self, bot) -> list[Point2]:
        top, barracks_pos, bottom = self._ramp_reference_points(bot)
        start = getattr(bot, "start_location", None)
        if start is None or top is None or bottom is None:
            return []
        try:
            nat = bot.mediator.get_own_nat
        except Exception:
            nat = None
        axis_x = float(bottom.x) - float(top.x)
        axis_y = float(bottom.y) - float(top.y)
        axis_len = math.hypot(axis_x, axis_y)
        if axis_len <= 0.01:
            return []
        axis_x /= axis_len
        axis_y /= axis_len
        perp_left = Point2((-axis_y, axis_x))
        perp_right = Point2((axis_y, -axis_x))
        out: list[Point2] = []
        centers = list(self._main_wall_bunker_slots(bot))
        for extra in (barracks_pos, top):
            if extra is None:
                continue
            duplicate = False
            for center in centers:
                try:
                    if float(center.distance_to(extra)) <= 1.0:
                        duplicate = True
                        break
                except Exception:
                    continue
            if not duplicate:
                centers.append(extra)
        for center in centers:
            side_dirs = [perp_left, perp_right]
            if nat is not None:
                try:
                    left_score = float(center.towards(perp_left, 1.5).distance_to(nat))
                    right_score = float(center.towards(perp_right, 1.5).distance_to(nat))
                    side_dirs = [perp_left, perp_right] if left_score <= right_score else [perp_right, perp_left]
                except Exception:
                    pass
            for back_dist in (0.75, 1.5, 2.25):
                try:
                    back_point = center.towards(start, back_dist)
                except Exception:
                    continue
                out.append(back_point)
                for side_dir in side_dirs:
                    for side_dist in (0.75, 1.5, 2.25):
                        try:
                            out.append(
                                Point2(
                                    (
                                        float(back_point.x) + (float(side_dir.x) * float(side_dist)),
                                        float(back_point.y) + (float(side_dir.y) * float(side_dist)),
                                    )
                                )
                            )
                        except Exception:
                            continue
        return out

    def _main_ramp_bunker_position(self, bot, *, anchor: Point2) -> Point2 | None:
        top, barracks_pos, bottom = self._ramp_reference_points(bot)
        candidate_centers = self._main_ramp_probe_targets(bot, anchor=anchor)
        if not candidate_centers:
            return None
        start = getattr(bot, "start_location", None)
        lowground_h = self._height(bot, bottom)
        highground_h = max(self._height(bot, top), self._height(bot, anchor), self._height(bot, start))
        wall_positions = self._wall_reserved_positions(bot)
        best: tuple[float, Point2] | None = None
        for center in candidate_centers:
            for radius, steps in ((0.0, 1), (1.5, 8), (2.5, 12), (3.5, 16), (4.5, 20)):
                for idx in range(steps):
                    angle = 0.0 if steps == 1 else ((2.0 * math.pi * float(idx)) / float(steps))
                    probe = Point2(
                        (
                            float(center.x) + (float(radius) * math.cos(angle)),
                            float(center.y) + (float(radius) * math.sin(angle)),
                        )
                    )
                    try:
                        if not bool(bot.in_pathing_grid(probe)):
                            continue
                    except Exception:
                        pass
                    try:
                        if not bool(
                            bot.mediator.can_place_structure(
                                position=probe,
                                structure_type=U.BUNKER,
                            )
                        ):
                            continue
                    except Exception:
                        continue
                    if self._conflicts_with_wall(probe, wall_positions, min_dist=2.0):
                        continue
                    score = 0.0
                    try:
                        probe_h = self._height(bot, probe)
                        if probe_h <= (float(lowground_h) + 0.25):
                            continue
                        if highground_h > -9990.0 and probe_h < (float(highground_h) - 0.75):
                            continue
                        if bottom is not None and float(probe.distance_to(bottom)) > 7.5:
                            continue
                        if top is not None and float(probe.distance_to(top)) > 7.0:
                            continue
                        edge_depth = self._ramp_edge_depth(bot, pos=probe, bottom=bottom, lowground_h=lowground_h)
                        if edge_depth > 4.5:
                            continue
                        if top is not None:
                            score += max(0.0, 12.0 - float(probe.distance_to(top))) * 4.0
                        if barracks_pos is not None:
                            score += max(0.0, 10.0 - float(probe.distance_to(barracks_pos))) * 2.5
                        if bottom is not None:
                            score += max(0.0, 12.0 - float(probe.distance_to(bottom))) * 1.8
                            score -= max(0.0, float(probe.distance_to(bottom)) - 4.5) * 2.5
                        if edge_depth < 1.0:
                            score -= 6.0
                        else:
                            score += max(0.0, 3.5 - abs(float(edge_depth) - 2.25)) * 3.0
                        if start is not None:
                            # Reject positions tucked too deep into the main.
                            score -= max(0.0, 10.0 - float(probe.distance_to(start))) * 4.5
                        if top is not None and start is not None:
                            # Penalize lightly if bunker is deeper than ramp top (farther from ramp).
                            score -= max(0.0, float(probe.distance_to(top)) - 4.0) * 2.5
                    except Exception:
                        pass
                    if best is None or score > best[0]:
                        best = (float(score), probe)
        return best[1] if best is not None else None

    def _is_valid_main_ramp_bunker_pos(self, bot, *, pos: Point2, anchor: Point2) -> bool:
        top, barracks_pos, bottom = self._ramp_reference_points(bot)
        start = getattr(bot, "start_location", None)
        lowground_h = self._height(bot, bottom)
        highground_h = max(self._height(bot, top), self._height(bot, anchor), self._height(bot, start))
        exact_wall_slot = self._is_exact_main_wall_bunker_slot(bot, pos=pos)
        try:
            if not bool(bot.in_pathing_grid(pos)):
                return False
        except Exception:
            pass
        try:
            if not bool(bot.mediator.can_place_structure(position=pos, structure_type=U.BUNKER)):
                return False
        except Exception:
            return False
        if (not exact_wall_slot) and self._conflicts_with_wall(pos, self._wall_reserved_positions(bot), min_dist=1.25):
            return False
        pos_h = self._height(bot, pos)
        if pos_h <= (float(lowground_h) + 0.25):
            return False
        if highground_h > -9990.0 and pos_h < (float(highground_h) - 0.75):
            return False
        if bottom is not None and float(pos.distance_to(bottom)) > (8.25 if exact_wall_slot else 7.5):
            return False
        if top is not None and float(pos.distance_to(top)) > (8.0 if exact_wall_slot else 7.0):
            return False
        if start is not None and top is not None:
            try:
                if float(pos.distance_to(start)) < (float(top.distance_to(start)) - 0.75):
                    return False
            except Exception:
                pass
        if (not exact_wall_slot) and barracks_pos is not None and top is not None:
            try:
                if float(pos.distance_to(barracks_pos)) > 8.5 and float(pos.distance_to(top)) > 5.5:
                    return False
            except Exception:
                return False
        edge_depth = self._ramp_edge_depth(bot, pos=pos, bottom=bottom, lowground_h=lowground_h)
        if edge_depth > (5.25 if exact_wall_slot else 4.5):
            return False
        return True

    @staticmethod
    def _wall_reserved_positions(bot) -> list[Point2]:
        """Retorna posições reservadas pela wall (depots e barracks) para evitar conflito."""
        try:
            ramp = getattr(bot, "main_base_ramp", None)
            if ramp is None:
                return []
            depots = list(getattr(ramp, "corner_depots", []) or [])
            barracks_pos = getattr(ramp, "barracks_correct_placement", None)
            out = list(depots)
            if barracks_pos is not None:
                out.append(barracks_pos)
            return out
        except Exception:
            return []

    @staticmethod
    def _conflicts_with_wall(pos: Point2, wall_positions: list[Point2], min_dist: float = 2.0) -> bool:
        for wp in wall_positions:
            try:
                if float(pos.distance_to(wp)) < float(min_dist):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _building_tracker(bot) -> dict:
        try:
            return dict(bot.mediator.get_building_tracker_dict or {})
        except Exception:
            return {}

    def _is_blocked_position(self, pos: Point2 | None) -> bool:
        if pos is None:
            return False
        for blocked in list(self._blocked_positions or []):
            try:
                if float(blocked.distance_to(pos)) <= 0.9:
                    return True
            except Exception:
                continue
        return False

    def _remember_blocked_position(self, pos: Point2 | None) -> None:
        if pos is None or self._is_blocked_position(pos):
            return
        blocked = list(self._blocked_positions or [])
        blocked.append(pos)
        self._blocked_positions = blocked[-8:]

    def _intel_main_ramp_bunker_pos(self, *, now: float) -> Point2 | None:
        if self.awareness is None:
            return None
        payload = self.awareness.mem.get(K("intel", "placements", "main_ramp_bunker"), now=now, default=None)
        if not isinstance(payload, dict):
            return None
        try:
            return Point2((float(payload.get("x", 0.0) or 0.0), float(payload.get("y", 0.0) or 0.0)))
        except Exception:
            return None

    def _bunker_started_or_ready(self, bot, *, base_pos: Point2) -> bool:
        anchor = self._bunker_anchor(bot, base_pos=base_pos)
        use_anchor = str(self.anchor_mode or "BASE").upper() in {"MAIN_RAMP", "NAT_CHOKE"}
        ref_pos = anchor if use_anchor else base_pos
        ref_radius = 14.0 if use_anchor else 16.0
        try:
            for b in bot.structures(U.BUNKER):
                if float(b.distance_to(ref_pos)) <= float(ref_radius):
                    return True
        except Exception:
            pass
        for entry in self._building_tracker(bot).values():
            if not isinstance(entry, dict):
                continue
            if entry.get("structure_type", None) != U.BUNKER:
                continue
            pos = entry.get("target", None) or entry.get("pos", None)
            if pos is None:
                continue
            try:
                if float(pos.distance_to(ref_pos)) <= float(ref_radius):
                    return True
            except Exception:
                continue
        # Verifica SCVs com ordem de construir bunker (build order pode não usar building_tracker)
        try:
            for scv in bot.units(U.SCV):
                for order in list(getattr(scv, "orders", []) or []):
                    ability_name = str(getattr(getattr(order, "ability", None), "name", "") or "").upper()
                    if "BUNKER" not in ability_name and "TERRANBUILD" not in ability_name:
                        continue
                    target = getattr(order, "target", None)
                    if target is None:
                        continue
                    try:
                        target_pos = Point2((float(target.x), float(target.y))) if hasattr(target, "x") else None
                        if target_pos is not None and float(target_pos.distance_to(ref_pos)) <= float(ref_radius):
                            return True
                    except Exception:
                        continue
        except Exception:
            pass
        return False

    async def _choose_bunker_position(self, bot, *, base_pos: Point2, anchor: Point2, now: float) -> Point2 | None:
        mode = str(self.anchor_mode or "BASE").upper()
        if mode == "MAIN_RAMP":
            wall_slots = self._main_wall_bunker_slots(bot)
            intel_pos = self._intel_main_ramp_bunker_pos(now=now)
            if (
                intel_pos is not None
                and not self._is_blocked_position(intel_pos)
                and self._is_valid_main_ramp_bunker_pos(bot, pos=intel_pos, anchor=anchor)
            ):
                return intel_pos
            for target in self._main_ramp_highground_targets(bot, anchor=anchor):
                try:
                    pos = await bot.find_placement(U.BUNKER, near=target, max_distance=2)
                    if (
                        pos is not None
                        and not self._is_blocked_position(pos)
                        and self._is_valid_main_ramp_bunker_pos(bot, pos=pos, anchor=anchor)
                    ):
                        return pos
                except Exception:
                    continue
            for slot in wall_slots:
                if self._is_blocked_position(slot):
                    continue
                if self._is_valid_main_ramp_bunker_pos(bot, pos=slot, anchor=anchor):
                    return slot
            for target in self._main_wall_fallback_targets(bot):
                try:
                    pos = await bot.find_placement(U.BUNKER, near=target, max_distance=2)
                    if (
                        pos is not None
                        and not self._is_blocked_position(pos)
                        and self._is_valid_main_ramp_bunker_pos(bot, pos=pos, anchor=anchor)
                    ):
                        return pos
                except Exception:
                    continue
            if wall_slots:
                for target in self._main_wall_fallback_targets(bot):
                    try:
                        pos = await bot.find_placement(U.BUNKER, near=target, max_distance=3)
                        if (
                            pos is not None
                            and not self._is_blocked_position(pos)
                            and self._is_valid_main_ramp_bunker_pos(bot, pos=pos, anchor=anchor)
                        ):
                            return pos
                    except Exception:
                        continue
                return None
            pos = self._main_ramp_bunker_position(bot, anchor=anchor)
            if (
                pos is not None
                and not self._is_blocked_position(pos)
                and self._is_valid_main_ramp_bunker_pos(bot, pos=pos, anchor=anchor)
            ):
                return pos
            for target in self._main_ramp_highground_targets(bot, anchor=anchor):
                try:
                    pos = await bot.find_placement(U.BUNKER, near=target, max_distance=4)
                    if (
                        pos is not None
                        and not self._is_blocked_position(pos)
                        and self._is_valid_main_ramp_bunker_pos(bot, pos=pos, anchor=anchor)
                    ):
                        return pos
                except Exception:
                    continue
            for target in self._main_ramp_probe_targets(bot, anchor=anchor):
                try:
                    pos = await bot.find_placement(U.BUNKER, near=target, max_distance=3)
                    if (
                        pos is not None
                        and not self._is_blocked_position(pos)
                        and self._is_valid_main_ramp_bunker_pos(bot, pos=pos, anchor=anchor)
                    ):
                        return pos
                except Exception:
                    continue
            # Fallback: tenta perto do anchor (top_center da rampa) antes de usar slots genéricos da main.
            try:
                pos = await bot.find_placement(U.BUNKER, near=anchor, max_distance=6)
                if (
                    pos is not None
                    and not self._is_blocked_position(pos)
                    and self._is_valid_main_ramp_bunker_pos(bot, pos=pos, anchor=anchor)
                ):
                    return pos
            except Exception:
                pass
            return None
        if mode == "NAT_CHOKE":
            try:
                pos = await bot.find_placement(U.BUNKER, near=anchor, max_distance=6)
                if pos is not None and not self._is_blocked_position(pos):
                    return pos
            except Exception:
                pass
        try:
            pos = bot.mediator.request_building_placement(
                base_location=(bot.start_location if mode == "MAIN_RAMP" else base_pos),
                structure_type=U.BUNKER,
                bunker=True,
                closest_to=anchor,
                reserve_placement=False,
            )
            if pos is not None and not self._is_blocked_position(pos):
                return pos
        except Exception:
            pass
        try:
            pos = bot.mediator.request_building_placement(
                base_location=base_pos,
                structure_type=U.BUNKER,
                bunker=False,
                closest_to=anchor,
                reserve_placement=False,
            )
            if pos is not None and not self._is_blocked_position(pos):
                return pos
        except Exception:
            pass
        try:
            pos = await bot.find_placement(U.BUNKER, near=anchor, max_distance=8)
            if pos is not None and not self._is_blocked_position(pos):
                return pos
            return None
        except Exception:
            return None

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound(exact_tags=1)
        if bound_err is not None:
            return bound_err
        worker = bot.units.find_by_tag(int(self.assigned_tags[0]))
        if worker is None:
            return TaskResult.failed("bunker_worker_missing")
        if getattr(worker, "type_id", None) != U.SCV:
            return TaskResult.failed("bunker_worker_not_scv")

        base_pos = self._resolve_base_pos(bot)
        if self._bunker_started_or_ready(bot, base_pos=base_pos):
            self._release_worker(bot, worker)
            self._done("bunker_ready_or_started")
            return TaskResult.done("bunker_ready_or_started")

        now = float(tick.time)
        anchor = self._bunker_anchor(bot, base_pos=base_pos)
        pos = self._target_pos
        if pos is None:
            pos = await self._choose_bunker_position(bot, base_pos=base_pos, anchor=anchor, now=now)
            self._target_pos = pos
        if pos is None:
            self._release_worker(bot, worker)
            self._done("bunker_position_unavailable")
            return TaskResult.done("bunker_position_unavailable")
        try:
            if float(worker.distance_to(pos)) > 6.0:
                worker.move(pos)
                self._active("moving_to_bunker_site")
                return TaskResult.running("moving_to_bunker_site")
        except Exception:
            pass
        if float(now) < float(self._next_issue_at):
            self._active("waiting_bunker_retry_window")
            return TaskResult.running("waiting_bunker_retry_window")
        try:
            if bool(
                bot.mediator.build_with_specific_worker(
                    worker=worker,
                    structure_type=U.BUNKER,
                    pos=pos,
                )
            ):
                self._issue_attempts = 0
                self._next_issue_at = float(now) + 0.45
                self._active("building_defense_bunker")
                return TaskResult.running("building_defense_bunker")
        except Exception:
            self._release_worker(bot, worker)
            self._done("bunker_build_command_failed")
            return TaskResult.done("bunker_build_command_failed")
        self._issue_attempts += 1
        self._next_issue_at = float(now) + 0.55
        self._remember_blocked_position(pos)
        self._target_pos = None
        try:
            worker.move(pos)
        except Exception:
            pass
        if int(self._issue_attempts) >= 16:
            self._release_worker(bot, worker)
            self._done("bunker_build_command_rejected")
            return TaskResult.done("bunker_build_command_rejected")
        self._active("retrying_bunker_build")
        return TaskResult.running("retrying_bunker_build")

from __future__ import annotations

from dataclasses import dataclass

from ares.consts import BuildingSize
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class MaintainWallTask(BaseTask):
    awareness: Awareness
    zone: str
    log: DevLogger | None = None

    def __init__(
        self,
        *,
        awareness: Awareness,
        zone: str,
        log: DevLogger | None = None,
    ) -> None:
        super().__init__(task_id=f"maintain_wall_{zone}", domain="DEFENSE", commitment=55)
        self.awareness = awareness
        self.zone = str(zone).lower()
        self.log = log

    @staticmethod
    def _distance(a, b) -> float:
        try:
            return float(a.distance_to(b))
        except Exception:
            return 9999.0

    @staticmethod
    def _building_tracker(bot) -> dict:
        try:
            return dict(bot.mediator.get_building_tracker_dict or {})
        except Exception:
            return {}

    @staticmethod
    def _placements_dict(bot) -> dict:
        try:
            return dict(bot.mediator.get_placements_dict or {})
        except Exception:
            return {}

    def _tracked_or_built(self, bot, *, structure_types: set, target: Point2, radius: float) -> int:
        total = 0
        for s in list(getattr(bot, "structures", []) or []):
            try:
                if s.type_id in structure_types and self._distance(s.position, target) <= float(radius):
                    total += 1
            except Exception:
                continue
        tracker = self._building_tracker(bot)
        for entry in tracker.values():
            if not isinstance(entry, dict):
                continue
            stype = entry.get("structure_type", None)
            pos = entry.get("target", None) or entry.get("pos", None)
            try:
                if stype in structure_types and pos is not None and self._distance(pos, target) <= float(radius):
                    total += 1
            except Exception:
                continue
        return int(total)

    def _missing_exact_targets(
        self,
        bot,
        *,
        targets: list[Point2],
        structure_types: set,
        radius: float,
    ) -> list[Point2]:
        missing: list[Point2] = []
        for pos in list(targets or []):
            if self._tracked_or_built(bot, structure_types=structure_types, target=pos, radius=radius) <= 0:
                missing.append(pos)
        return missing

    def _issue_exact_build(self, bot, *, structure_type: U, pos: Point2) -> bool:
        try:
            if not bool(bot.can_afford(structure_type)):
                return False
        except Exception:
            return False
        try:
            worker = bot.mediator.select_worker(target_position=pos, force_close=True)
            if worker is None:
                return False
            return bool(
                bot.mediator.build_with_specific_worker(
                    worker=worker,
                    structure_type=structure_type,
                    pos=pos,
                )
            )
        except Exception:
            return False

    def _wall_positions(
        self,
        bot,
        *,
        base_location: Point2,
        size: BuildingSize,
        require_supply_depot: bool = False,
    ) -> list[Point2]:
        placements = self._placements_dict(bot)
        if base_location not in placements:
            return []
        per_size = placements[base_location].get(size, {}) or {}
        out: list[Point2] = []
        for pos, info in per_size.items():
            if not isinstance(info, dict):
                continue
            if not bool(info.get("is_wall", False)):
                continue
            if bool(info.get("bunker", False)):
                continue
            if bool(require_supply_depot) and not bool(info.get("supply_depot", False)):
                continue
            out.append(pos)
        return out

    def _nat_active(self, bot) -> bool:
        try:
            nat = bot.mediator.get_own_nat
        except Exception:
            return False
        for th in list(getattr(bot, "townhalls", []) or []):
            try:
                if self._distance(th.position, nat) <= 8.0:
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _rush_active(*, awareness: Awareness, now: float) -> bool:
        state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        return state in {"SUSPECTED", "CONFIRMED", "HOLDING"}

    @staticmethod
    def _main_wall_barracks(bot, *, barracks_pos: Point2 | None):
        if barracks_pos is None:
            return None
        candidates = []
        for s in list(getattr(bot, "structures", []) or []):
            try:
                if s.type_id not in {U.BARRACKS, U.BARRACKSFLYING}:
                    continue
                if float(s.distance_to(barracks_pos)) <= 2.5:
                    candidates.append(s)
            except Exception:
                continue
        if not candidates:
            return None
        try:
            candidates.sort(key=lambda s: float(s.distance_to(barracks_pos)))
        except Exception:
            pass
        return candidates[0]

    def _main_wall_reactor_started_or_ready(self, bot, *, barracks_pos: Point2 | None) -> bool:
        wall_rax = self._main_wall_barracks(bot, barracks_pos=barracks_pos)
        if wall_rax is not None:
            try:
                if int(getattr(wall_rax, "add_on_tag", 0) or 0) != 0:
                    return True
            except Exception:
                pass
        tracker = self._building_tracker(bot)
        for entry in tracker.values():
            if not isinstance(entry, dict):
                continue
            if entry.get("structure_type", None) != U.BARRACKSREACTOR:
                continue
            pos = entry.get("target", None) or entry.get("pos", None)
            if pos is None or barracks_pos is None:
                continue
            try:
                if self._distance(pos, barracks_pos) <= 4.5:
                    return True
            except Exception:
                continue
        try:
            for rx in list(bot.structures(U.BARRACKSREACTOR)):
                if barracks_pos is not None and self._distance(rx.position, barracks_pos) <= 4.5:
                    return True
        except Exception:
            pass
        return False

    def _issue_main_wall_reactor(self, bot, *, barracks_pos: Point2 | None) -> bool:
        wall_rax = self._main_wall_barracks(bot, barracks_pos=barracks_pos)
        if wall_rax is None:
            return False
        try:
            if not bool(getattr(wall_rax, "is_ready", False)):
                return False
            if bool(getattr(wall_rax, "is_flying", False)):
                return False
            if int(getattr(wall_rax, "add_on_tag", 0) or 0) != 0:
                return False
            if not bool(getattr(wall_rax, "is_idle", True)):
                return False
            if not bool(bot.can_afford(U.BARRACKSREACTOR)):
                return False
            wall_rax(AbilityId.BUILD_REACTOR_BARRACKS)
            return True
        except Exception:
            return False

    def _maintain_main(self, bot, *, attention: Attention, now: float) -> TaskResult:
        ramp = bot.main_base_ramp
        depot_positions = list(getattr(ramp, "corner_depots", []) or [])
        barracks_pos = getattr(ramp, "barracks_correct_placement", None)
        rush_active = bool(self._rush_active(awareness=self.awareness, now=now))
        main_wall_enemy_near = False
        try:
            if ramp is not None:
                wall_center = getattr(ramp, "top_center", None) or bot.start_location
                main_wall_enemy_near = int(bot.enemy_units.closer_than(10.0, wall_center).amount) > 0
        except Exception:
            main_wall_enemy_near = False
        missing_depots = self._missing_exact_targets(
            bot,
            targets=depot_positions,
            structure_types={U.SUPPLYDEPOT, U.SUPPLYDEPOTLOWERED},
            radius=1.6,
        )
        depots_done = max(0, len(depot_positions) - len(missing_depots))
        missing_three_by_three: list[Point2] = []
        if barracks_pos is not None:
            missing_three_by_three = self._missing_exact_targets(
                bot,
                targets=[barracks_pos],
                structure_types={U.BARRACKS, U.BARRACKSFLYING, U.FACTORY, U.FACTORYFLYING},
                radius=2.2,
            )
        three_by_three_done = 0 if missing_three_by_three else (1 if barracks_pos is not None else 0)
        reactor_required = bool(
            rush_active
            and barracks_pos is not None
            and depots_done >= len(depot_positions)
            and int(three_by_three_done) >= 1
        )
        reactor_started = bool(self._main_wall_reactor_started_or_ready(bot, barracks_pos=barracks_pos)) if reactor_required else False
        self.awareness.mem.set(
            K("ops", "wall", "main", "status"),
            value={
                "depots_done": int(depots_done),
                "depots_expected": int(len(depot_positions)),
                "three_by_three_done": int(three_by_three_done),
                "reactor_required": bool(reactor_required),
                "reactor_started": bool(reactor_started),
                "enemy_near": bool(main_wall_enemy_near),
                "complete": bool(
                    depots_done >= len(depot_positions)
                    and three_by_three_done >= 1
                    and ((not reactor_required) or bool(reactor_started))
                ),
                "updated_at": float(now),
            },
            now=now,
            ttl=8.0,
        )
        if float(now) >= 28.0 and missing_depots:
            if self._issue_exact_build(bot, structure_type=U.SUPPLYDEPOT, pos=missing_depots[0]):
                self._active("building_main_wall_depot")
                return TaskResult.running("building_main_wall_depot")
        if float(now) >= 38.0 and missing_three_by_three:
            if self._issue_exact_build(bot, structure_type=U.BARRACKS, pos=missing_three_by_three[0]):
                self._active("building_main_wall_three_by_three")
                return TaskResult.running("building_main_wall_three_by_three")
        if reactor_required and depots_done >= len(depot_positions) and int(three_by_three_done) >= 1 and not reactor_started:
            if self._issue_main_wall_reactor(bot, barracks_pos=barracks_pos):
                self._active("building_main_wall_reactor")
                return TaskResult.running("building_main_wall_reactor")
        if depots_done >= len(depot_positions) and int(three_by_three_done) >= 1 and ((not reactor_required) or reactor_started):
            self._done("main_wall_complete")
            return TaskResult.done("main_wall_complete")
        return TaskResult.noop("main_wall_wait")

    def _maintain_nat(self, bot, *, attention: Attention, now: float) -> TaskResult:
        if not self._nat_active(bot):
            return TaskResult.noop("nat_inactive")
        try:
            nat = bot.mediator.get_own_nat
        except Exception:
            return TaskResult.noop("nat_unknown")
        rush_state = str(self.awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        rush_active = rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}
        enemy_count = int(getattr(attention.combat, "primary_enemy_count", 0) or 0)
        if not rush_active and enemy_count <= 0:
            return TaskResult.noop("nat_fort_not_required")
        depot_targets = self._wall_positions(
            bot,
            base_location=nat,
            size=BuildingSize.TWO_BY_TWO,
            require_supply_depot=True,
        )
        three_by_three_targets = self._wall_positions(
            bot,
            base_location=nat,
            size=BuildingSize.THREE_BY_THREE,
            require_supply_depot=False,
        )
        if not depot_targets and not three_by_three_targets:
            self.awareness.mem.set(
                K("ops", "wall", "nat", "status"),
                value={
                    "supported": False,
                    "reason": "no_custom_nat_wall_placements",
                    "depots_expected": 0,
                    "depots_done": 0,
                    "three_by_three_expected": 0,
                    "three_by_three_done": 0,
                    "complete": False,
                    "updated_at": float(now),
                },
                now=now,
                ttl=8.0,
            )
            self._done("nat_wall_not_configured")
            return TaskResult.done("nat_wall_not_configured")
        missing_depots = self._missing_exact_targets(
            bot,
            targets=depot_targets,
            structure_types={U.SUPPLYDEPOT, U.SUPPLYDEPOTLOWERED},
            radius=1.6,
        )
        missing_three_by_three = self._missing_exact_targets(
            bot,
            targets=three_by_three_targets,
            structure_types={
                U.BARRACKS,
                U.BARRACKSFLYING,
                U.FACTORY,
                U.FACTORYFLYING,
                U.ENGINEERINGBAY,
                U.ARMORY,
                U.GHOSTACADEMY,
                U.FUSIONCORE,
            },
            radius=2.2,
        )
        depot_count = max(0, len(depot_targets) - len(missing_depots))
        three_by_three_done = max(0, len(three_by_three_targets) - len(missing_three_by_three))
        self.awareness.mem.set(
            K("ops", "wall", "nat", "status"),
            value={
                "supported": True,
                "depots_expected": int(len(depot_targets)),
                "depots_done": int(depot_count),
                "three_by_three_expected": int(len(three_by_three_targets)),
                "three_by_three_done": int(three_by_three_done),
                "complete": bool(
                    int(depot_count) >= int(len(depot_targets))
                    and int(three_by_three_done) >= int(len(three_by_three_targets))
                ),
                "updated_at": float(now),
            },
            now=now,
            ttl=8.0,
        )
        if missing_three_by_three:
            if self._issue_exact_build(bot, structure_type=U.BARRACKS, pos=missing_three_by_three[0]):
                self._active("building_nat_wall_three_by_three")
                return TaskResult.running("building_nat_wall_three_by_three")
        if missing_depots:
            if self._issue_exact_build(bot, structure_type=U.SUPPLYDEPOT, pos=missing_depots[0]):
                self._active("building_nat_depot")
                return TaskResult.running("building_nat_depot")
        if (
            int(depot_count) >= int(len(depot_targets))
            and int(three_by_three_done) >= int(len(three_by_three_targets))
        ):
            self._done("nat_wall_complete")
            return TaskResult.done("nat_wall_complete")
        return TaskResult.noop("nat_wall_wait")

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound()
        if bound_err is not None:
            return bound_err
        now = float(tick.time)
        if self.zone == "main":
            return self._maintain_main(bot, attention=attention, now=now)
        if self.zone == "nat":
            return self._maintain_nat(bot, attention=attention, now=now)
        return TaskResult.failed("unknown_wall_zone")

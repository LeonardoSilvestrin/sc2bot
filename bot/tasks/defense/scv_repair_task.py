from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class ScvRepairTask(BaseTask):
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
        super().__init__(task_id="scv_repair", domain="DEFENSE", commitment=75)
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
    def _main_wall_targets(bot) -> list:
        try:
            ramp = getattr(bot, "main_base_ramp", None)
            if ramp is None:
                return []
            depot_positions = list(getattr(ramp, "corner_depots", []) or [])
            barracks_pos = getattr(ramp, "barracks_correct_placement", None)
        except Exception:
            return []

        wall_targets = []
        for s in list(getattr(bot, "structures", []) or []):
            try:
                tid = getattr(s, "type_id", None)
                if tid not in {U.SUPPLYDEPOT, U.SUPPLYDEPOTLOWERED, U.BARRACKS, U.BARRACKSREACTOR, U.BARRACKSTECHLAB}:
                    continue
                if any(float(s.distance_to(pos)) <= 1.8 for pos in depot_positions):
                    wall_targets.append(s)
                    continue
                if barracks_pos is not None and float(s.distance_to(barracks_pos)) <= 2.4:
                    wall_targets.append(s)
            except Exception:
                continue
        return wall_targets

    @staticmethod
    def _repair_priority(unit) -> tuple[int, float]:
        tid = getattr(unit, "type_id", None)
        hp_gap = float((getattr(unit, "health_max", 0.0) or 0.0) - (getattr(unit, "health", 0.0) or 0.0))
        try:
            is_main_wall = bool(getattr(unit, "_scv_repair_main_wall", False))
        except Exception:
            is_main_wall = False
        if is_main_wall:
            return (6, hp_gap)
        if tid == U.BUNKER:
            return (5, hp_gap)
        if tid in {U.SIEGETANK, U.SIEGETANKSIEGED}:
            return (4, hp_gap)
        if tid in {U.COMMANDCENTER, U.ORBITALCOMMAND, U.PLANETARYFORTRESS}:
            return (3, hp_gap)
        if tid in {U.BARRACKS, U.BARRACKSREACTOR, U.BARRACKSTECHLAB, U.SUPPLYDEPOT, U.SUPPLYDEPOTLOWERED}:
            return (2, hp_gap)
        return (1, hp_gap)

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
        try:
            scv.move(target.position)
            return True
        except Exception:
            return False

    def _repair_targets(self, bot, *, base_pos: Point2) -> list:
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
        out = []
        for unit in list(getattr(bot, "structures", []) or []) + list(getattr(bot, "units", []) or []):
            try:
                if unit.type_id not in allowed:
                    continue
                if float(unit.distance_to(base_pos)) > 16.0:
                    continue
                hp = float(getattr(unit, "health", 0.0) or 0.0)
                hp_max = float(getattr(unit, "health_max", 0.0) or 0.0)
                build_progress = float(getattr(unit, "build_progress", 1.0) or 1.0)
                if hp_max <= 0.0:
                    continue
                if hp < hp_max or build_progress < 1.0:
                    out.append(unit)
            except Exception:
                continue
        main_bias = False
        try:
            main_bias = float(base_pos.distance_to(bot.start_location)) <= 10.0
        except Exception:
            main_bias = False
        if main_bias:
            for wall_unit in self._main_wall_targets(bot):
                try:
                    hp = float(getattr(wall_unit, "health", 0.0) or 0.0)
                    hp_max = float(getattr(wall_unit, "health_max", 0.0) or 0.0)
                    build_progress = float(getattr(wall_unit, "build_progress", 1.0) or 1.0)
                    if hp_max <= 0.0 or (hp >= hp_max and build_progress >= 1.0):
                        continue
                    setattr(wall_unit, "_scv_repair_main_wall", True)
                    if wall_unit not in out:
                        out.append(wall_unit)
                except Exception:
                    continue
        out.sort(key=self._repair_priority, reverse=True)
        return out

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound(min_tags=1)
        if bound_err is not None:
            return bound_err

        units = [bot.units.find_by_tag(int(t)) for t in self.assigned_tags]
        units = [u for u in units if u is not None and u.type_id == U.SCV]
        if not units:
            return TaskResult.failed("no_repair_scvs_alive")

        base_pos = self._resolve_base_pos(bot)
        targets = self._repair_targets(bot, base_pos=base_pos)
        if not targets:
            self._done("repair_targets_cleared")
            return TaskResult.done("repair_targets_cleared")

        issued = False
        for scv in units:
            ranked_targets = list(targets)
            try:
                ranked_targets.sort(
                    key=lambda target: (
                        -self._repair_priority(target)[0],
                        -self._repair_priority(target)[1],
                        float(scv.distance_to(target)),
                    )
                )
            except Exception:
                pass
            target = ranked_targets[0] if ranked_targets else None
            if target is None:
                continue
            issued = self._issue_repair(scv, target) or issued

        if issued:
            self._active("scv_repair_active")
            return TaskResult.running("scv_repair_active")
        self._active("scv_repair_hold")
        return TaskResult.noop("scv_repair_hold")

from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class LandBaseTask(BaseTask):
    awareness: Awareness
    base_label: str
    target_pos: Point2
    log: DevLogger | None = None

    def __init__(
        self,
        *,
        awareness: Awareness,
        base_label: str,
        target_pos: Point2,
        log: DevLogger | None = None,
    ) -> None:
        super().__init__(task_id=f"land_base_{str(base_label).lower()}", domain="DEFENSE", commitment=76)
        self.awareness = awareness
        self.base_label = str(base_label)
        self.target_pos = target_pos
        self.log = log

    @staticmethod
    def _registry_entry(awareness: Awareness, *, now: float, label: str) -> dict:
        registry = awareness.mem.get(K("intel", "our_bases", "registry"), now=now, default={}) or {}
        if not isinstance(registry, dict):
            return {}
        entry = registry.get(str(label), {})
        return dict(entry) if isinstance(entry, dict) else {}

    @staticmethod
    def _nat_snapshot(awareness: Awareness, *, now: float) -> dict:
        snapshot = awareness.mem.get(K("intel", "map_control", "our_nat", "snapshot"), now=now, default={}) or {}
        return dict(snapshot) if isinstance(snapshot, dict) else {}

    def _target_unit(self, bot, *, now: float):
        entry = self._registry_entry(self.awareness, now=now, label=self.base_label)
        tag = int(entry.get("townhall_tag", 0) or 0)
        if tag > 0:
            try:
                unit = bot.townhalls.find_by_tag(tag)
                if unit is not None:
                    return unit
            except Exception:
                pass
            try:
                for struct in list(getattr(bot, "structures", []) or []):
                    if int(getattr(struct, "tag", -1) or -1) == int(tag):
                        return struct
            except Exception:
                pass

        fallback_types = {
            U.COMMANDCENTER,
            U.ORBITALCOMMAND,
            U.COMMANDCENTERFLYING,
            U.ORBITALCOMMANDFLYING,
        }
        is_natural_recovery = str(self.base_label).upper() == "NATURAL"
        all_candidates = list(getattr(bot, "townhalls", []) or []) + list(getattr(bot, "structures", []) or [])
        seen_tags: set[int] = set()
        flying_best = None
        flying_best_score = 9999.0
        grounded_best = None
        grounded_best_score = 9999.0
        for unit in all_candidates:
            try:
                if getattr(unit, "type_id", None) not in fallback_types:
                    continue
                tag = int(getattr(unit, "tag", -1) or -1)
                if tag in seen_tags:
                    continue
                seen_tags.add(tag)
                dist_target = float(unit.distance_to(self.target_pos))
                dist_main = float(unit.distance_to(bot.start_location))
                is_flying = bool(getattr(unit, "is_flying", False))

                if is_flying:
                    score = dist_target - 6.0 + ((0.15 if is_natural_recovery else 0.35) * dist_main)
                    if score < flying_best_score:
                        flying_best_score = score
                        flying_best = unit
                    continue

                # Guardrail: during NATURAL recovery, never lift main as fallback.
                if is_natural_recovery:
                    if dist_target > 15.0:
                        continue
                    if dist_main <= 11.0:
                        continue
                score = dist_target + (0.35 * dist_main)
                if score < grounded_best_score:
                    grounded_best_score = score
                    grounded_best = unit
            except Exception:
                continue
        return flying_best or grounded_best

    def _clear_landing_zone(self, bot, *, target_pos: Point2, landing_unit_tag: int) -> bool:
        issued = False
        try:
            own_units = list(getattr(bot, "units", []) or [])
        except Exception:
            own_units = []
        for ally in own_units:
            try:
                if int(getattr(ally, "tag", -1) or -1) == int(landing_unit_tag):
                    continue
                if bool(getattr(ally, "is_flying", False)):
                    continue
                dist = float(ally.distance_to(target_pos))
                if dist > 4.5:
                    continue
                if getattr(ally, "type_id", None) == U.WIDOWMINEBURROWED:
                    ally(AbilityId.BURROWUP_WIDOWMINE)
                    issued = True
                    continue
                retreat = getattr(bot, "start_location", None)
                try:
                    if retreat is not None:
                        retreat = target_pos.towards(retreat, 6.0)
                except Exception:
                    retreat = getattr(bot, "start_location", None)
                if retreat is None:
                    continue
                ally.move(retreat)
                issued = True
            except Exception:
                continue
        return issued

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound()
        if bound_err is not None:
            return bound_err

        now = float(tick.time)
        snapshot = self._nat_snapshot(self.awareness, now=now)
        safe_to_land = bool(snapshot.get("safe_to_land", False))

        if not safe_to_land:
            return TaskResult.noop("landing_not_safe")

        unit = self._target_unit(bot, now=now)
        if unit is None:
            self._done("land_target_missing")
            return TaskResult.done("land_target_missing")

        try:
            if not bool(getattr(unit, "is_flying", False)):
                if float(unit.distance_to(self.target_pos)) <= 6.0:
                    self._done("base_landed")
                    return TaskResult.done("base_landed")
                if unit.type_id == U.COMMANDCENTER:
                    unit(AbilityId.LIFT_COMMANDCENTER)
                    self._active("lifting_base")
                    return TaskResult.running("lifting_base")
                if unit.type_id == U.ORBITALCOMMAND:
                    unit(AbilityId.LIFT_ORBITALCOMMAND)
                    self._active("lifting_base")
                    return TaskResult.running("lifting_base")
                self._done("base_grounded_offsite")
                return TaskResult.done("base_grounded_offsite")
        except Exception:
            self._done("base_grounded")
            return TaskResult.done("base_grounded")

        try:
            if float(unit.distance_to(self.target_pos)) > 3.5:
                unit.move(self.target_pos)
                self._active("flying_to_land_site")
                return TaskResult.running("flying_to_land_site")

            if self._clear_landing_zone(
                bot,
                target_pos=self.target_pos,
                landing_unit_tag=int(getattr(unit, "tag", -1) or -1),
            ):
                self._active("clearing_landing_zone")
                return TaskResult.running("clearing_landing_zone")

            if unit.type_id == U.COMMANDCENTERFLYING:
                unit(AbilityId.LAND_COMMANDCENTER, self.target_pos)
            elif unit.type_id == U.ORBITALCOMMANDFLYING:
                unit(AbilityId.LAND_ORBITALCOMMAND, self.target_pos)
            else:
                self._done("land_not_supported")
                return TaskResult.done("land_not_supported")

            self._active("landing_base")
            return TaskResult.running("landing_base")
        except Exception:
            self._done("land_command_failed")
            return TaskResult.done("land_command_failed")

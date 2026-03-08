from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ares.behaviors.macro.auto_supply import AutoSupply
from ares.behaviors.macro.expansion_controller import ExpansionController
from cython_extensions import cy_distance_to_squared
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.mind.awareness import Awareness, K


PRODUCTION_STRUCTURE_IDS: set[U] = {U.BARRACKS, U.FACTORY, U.STARPORT}
UPGRADE_STRUCTURE_IDS: set[U] = {
    U.ENGINEERINGBAY,
    U.ARMORY,
    U.FUSIONCORE,
    U.GHOSTACADEMY,
}


def point_to_payload(point: Point2, *, source: str) -> dict[str, Any]:
    return {
        "x": round(float(point.x), 2),
        "y": round(float(point.y), 2),
        "source": str(source),
    }


def payload_to_point(payload: Any) -> Point2 | None:
    if not isinstance(payload, dict):
        return None
    try:
        return Point2((float(payload.get("x", 0.0) or 0.0), float(payload.get("y", 0.0) or 0.0)))
    except Exception:
        return None


@dataclass
class BuildingPlacementPlanner:
    ttl_s: float = 12.0

    @staticmethod
    def _offsite_cc_anchor(bot, *, target: Point2 | None) -> Point2:
        try:
            ramp = getattr(bot, "main_base_ramp", None)
            top = getattr(ramp, "top_center", None) if ramp is not None else None
            if top is not None:
                return top.towards(bot.start_location, 6.0)
        except Exception:
            pass
        if target is not None:
            try:
                return target.towards(bot.start_location, 12.0)
            except Exception:
                pass
        return bot.start_location

    @staticmethod
    def _current_structure_count(bot, structure_id: U) -> int:
        try:
            ready = len([s for s in bot.mediator.get_own_structures_dict[structure_id] if getattr(s, "is_ready", False)])
        except Exception:
            ready = 0
        try:
            pending = int(bot.structure_pending(structure_id) or 0)
        except Exception:
            pending = 0
        return int(ready + pending)

    @staticmethod
    def _main_wall_complete(*, awareness: Awareness, now: float) -> bool:
        status = awareness.mem.get(K("ops", "wall", "main", "status"), now=now, default=None)
        if not isinstance(status, dict):
            return False
        return bool(status.get("complete", False))

    @staticmethod
    def _preview_flags(structure_id: U) -> dict[str, bool]:
        flags: dict[str, bool] = {}
        if structure_id == U.SUPPLYDEPOT:
            flags["supply_depot"] = True
        elif structure_id == U.BUNKER:
            flags["bunker"] = True
        elif structure_id == U.MISSILETURRET:
            flags["missile_turret"] = True
        elif structure_id == U.SENSORTOWER:
            flags["sensor_tower"] = True
        elif structure_id in PRODUCTION_STRUCTURE_IDS:
            flags["production"] = True
        elif structure_id in UPGRADE_STRUCTURE_IDS:
            flags["upgrade_structure"] = True
        return flags

    def _preview_structure(
        self,
        bot,
        *,
        structure_id: U,
        previous_signals: dict[str, Any],
        source: str,
    ) -> dict[str, Any] | None:
        anchor = payload_to_point(previous_signals.get(str(structure_id.name)))
        if anchor is None:
            anchor = bot.start_location
        try:
            point = bot.mediator.request_building_placement(
                base_location=bot.start_location,
                structure_type=structure_id,
                reserve_placement=False,
                find_alternative=True,
                closest_to=anchor,
                **self._preview_flags(structure_id),
            )
        except Exception:
            point = None
        if point is None:
            return None
        return point_to_payload(point, source=source)

    def _preview_expansion(self, bot, *, awareness: Awareness, previous_signals: dict[str, Any]) -> dict[str, Any] | None:
        mem = getattr(awareness, "mem", None)
        now = float(getattr(bot, "time", 0.0) or 0.0)
        registry = mem.get(K("intel", "our_bases", "registry"), now=now, default={}) if mem is not None else {}
        if not isinstance(registry, dict):
            registry = {}
        plan_active = mem.get(K("macro", "plan", "active"), now=now, default={}) if mem is not None else {}
        if not isinstance(plan_active, dict):
            plan_active = {}
        target_label = str(plan_active.get("expand_target_label", "") or "")
        build_mode = str(plan_active.get("expand_build_mode", "DIRECT") or "DIRECT").upper()
        if target_label:
            target_entry = registry.get(target_label, {})
            if isinstance(target_entry, dict):
                intended = payload_to_point(target_entry.get("intended_pos"))
                if intended is not None:
                    if build_mode == "OFFSITE":
                        return point_to_payload(self._offsite_cc_anchor(bot, target=intended), source="expand_offsite")
                    return point_to_payload(intended, source="expand_site")
        preferred = payload_to_point(previous_signals.get(str(bot.base_townhall_type.name)))
        try:
            expansions = list(bot.mediator.get_own_expansions or [])
        except Exception:
            expansions = []
        if not expansions:
            return None
        if preferred is not None:
            expansions.sort(key=lambda item: cy_distance_to_squared(item[0], preferred))
        try:
            grid = bot.mediator.get_ground_grid
        except Exception:
            grid = None
        for pos, _ in expansions:
            try:
                if grid is not None and not bot.mediator.is_position_safe(grid=grid, position=pos):
                    continue
            except Exception:
                pass
            try:
                if ExpansionController._location_is_blocked(bot.mediator, pos):
                    continue
            except Exception:
                pass
            return point_to_payload(pos, source="expand")
        return None

    def publish(self, *, bot, awareness: Awareness, now: float) -> dict[str, dict[str, Any]]:
        previous_signals = awareness.mem.get(K("macro", "placement", "signals"), now=now, default={}) or {}
        if not isinstance(previous_signals, dict):
            previous_signals = {}

        active_plan = awareness.mem.get(K("macro", "plan", "active"), now=now, default={}) or {}
        if not isinstance(active_plan, dict):
            active_plan = {}

        signals: dict[str, dict[str, Any]] = {}

        try:
            supply_required = int(AutoSupply._num_supply_required(bot, bot.mediator))
        except Exception:
            supply_required = 0
        if supply_required > 0 and self._main_wall_complete(awareness=awareness, now=now):
            payload = self._preview_structure(
                bot,
                structure_id=U.SUPPLYDEPOT,
                previous_signals=previous_signals,
                source="supply",
            )
            if payload is not None:
                signals[str(U.SUPPLYDEPOT.name)] = payload

        expand_to = int(active_plan.get("expand_to", 1) or 1)
        enable_expansion = bool(active_plan.get("enable_expansion", False))
        current_bases = self._current_structure_count(bot, bot.base_townhall_type)
        if enable_expansion and current_bases < expand_to:
            payload = self._preview_expansion(bot, awareness=awareness, previous_signals=previous_signals)
            if payload is not None:
                signals[str(bot.base_townhall_type.name)] = payload

        production_targets = awareness.mem.get(
            K("macro", "exec", "production_structure_targets_dynamic"),
            now=now,
            default={},
        ) or {}
        if isinstance(production_targets, dict):
            for name, target in production_targets.items():
                structure_id = getattr(U, str(name), None)
                if structure_id is None:
                    continue
                if self._current_structure_count(bot, structure_id) >= max(0, int(target or 0)):
                    continue
                payload = self._preview_structure(
                    bot,
                    structure_id=structure_id,
                    previous_signals=previous_signals,
                    source="production",
                )
                if payload is not None:
                    signals[str(structure_id.name)] = payload

        tech_targets = awareness.mem.get(K("tech", "exec", "targets"), now=now, default={}) or {}
        if isinstance(tech_targets, dict):
            tech_structures = tech_targets.get("structures", {})
            if isinstance(tech_structures, dict):
                for name, target in tech_structures.items():
                    structure_id = getattr(U, str(name), None)
                    if structure_id is None:
                        continue
                    if self._current_structure_count(bot, structure_id) >= max(0, int(target or 0)):
                        continue
                    payload = self._preview_structure(
                        bot,
                        structure_id=structure_id,
                        previous_signals=previous_signals,
                        source="tech",
                    )
                    if payload is not None:
                        signals[str(structure_id.name)] = payload

        awareness.mem.set(K("macro", "placement", "signals"), value=dict(signals), now=now, ttl=float(self.ttl_s))
        awareness.mem.set(
            K("macro", "placement", "status"),
            value={"count": int(len(signals)), "types": sorted(signals.keys())},
            now=now,
            ttl=float(self.ttl_s),
        )
        return signals

"""A persistent late-game sensor network, independent of Awareness."""

from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, BaseView
from bot.ego.missions import Lifecycle, MissionStatus, MissionView
from bot.ego.planners import SensorTowerPlan, SensorTowerSite

OWNER = "intel"
KIND = "sensor_towers"
MIN_BASES = 4
TOWER_OFFSET = 9.0
SITE_COVER_RADIUS = 12.0
SENSOR_TOWERS = frozenset({UnitTypeId.SENSORTOWER})
ENGINEERING_BAYS = frozenset({UnitTypeId.ENGINEERINGBAY})


class SensorTowerMission:
    BUILDING = "BUILDING"
    MAINTAINING = "MAINTAINING"

    def __init__(self, mission_id: str, now: float) -> None:
        self.lifecycle = Lifecycle(mission_id)
        self.phase = self.BUILDING
        self.since = now
        self.reason = "four_bases_reached"

    @property
    def mission_id(self) -> str:
        return self.lifecycle.mission_id

    @property
    def status(self) -> MissionStatus:
        return self.lifecycle.status

    @property
    def active(self) -> bool:
        return self.lifecycle.active

    def step(self, attention: AttentionState) -> SensorTowerPlan:
        sites = sensor_tower_sites(attention)
        towers = [
            structure.position
            for structure in attention.own_structures
            if structure.type_id in SENSOR_TOWERS
        ]
        missing = tuple(
            site
            for site in sites
            if not any(site.target.distance_to(tower) <= SITE_COVER_RADIUS for tower in towers)
        )
        engineering_bay = bool(missing) and not any(
            structure.type_id in ENGINEERING_BAYS for structure in attention.own_structures
        )
        phase = self.MAINTAINING if not missing else self.BUILDING
        reason = (
            "sensor_network_covered"
            if not missing
            else ("engineering_bay_needed" if engineering_bay else "sensor_tower_needed")
        )
        if phase != self.phase:
            self.phase, self.since = phase, attention.time
        self.reason = reason
        return SensorTowerPlan(
            sites=missing,
            engineering_bay=engineering_bay,
            reason=reason,
            inputs=(
                ("bases", float(len(attention.bases))),
                ("protected_bases", float(len(sites))),
                ("missing_towers", float(len(missing))),
            ),
        )

    def view(self) -> MissionView:
        return MissionView(
            mission_id=self.mission_id,
            owner=OWNER,
            kind=KIND,
            status=self.status,
            phase=self.phase,
            since=self.since,
            reason=self.reason,
            cancel=self.lifecycle.cancel,
            proposals=(),
            granted_units=0,
            granted_power=0.0,
        )


def sensor_tower_sites(attention: AttentionState) -> tuple[SensorTowerSite, ...]:
    bases = attention.bases
    if not bases:
        return ()
    main = min(
        bases,
        key=lambda base: (
            not base.is_main,
            base.position.distance_to(attention.map.own_start),
            base.base_id,
        ),
    )
    others = [base for base in bases if base.base_id != main.base_id]
    outer: list[BaseView] = []
    if others:
        distances = {base.base_id: base.position.distance_to(main.position) for base in others}
        farthest = max(distances.values())
        tolerance = max(1.0, attention.map.lattice_spacing)
        outer = [base for base in others if distances[base.base_id] >= farthest - tolerance]
    selected = [main, *sorted(outer, key=lambda base: base.base_id)]
    return tuple(_site(base, main, attention) for base in selected)


def _site(base: BaseView, main: BaseView, attention: AttentionState) -> SensorTowerSite:
    outward = (
        attention.map.enemy_start
        if base.base_id == main.base_id
        else Point2(
            (
                base.position.x + (base.position.x - main.position.x),
                base.position.y + (base.position.y - main.position.y),
            )
        )
    )
    target = base.position.towards(outward, TOWER_OFFSET)
    min_x, min_y, max_x, max_y = attention.map.bounds
    target = Point2(
        (
            min(max(target.x, min_x + 1.0), max_x - 1.0),
            min(max(target.y, min_y + 1.0), max_y - 1.0),
        )
    )
    return SensorTowerSite(base.base_id, base.position, target)

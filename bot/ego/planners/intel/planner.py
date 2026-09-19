"""Intel: scouting, detection and persistent information infrastructure.

What information matters most follows Strategy's posture, as this planner
reads it (`IntelPlan.focus`):

- `threat` (DEFEND): the threat is at home. No scout leaves while it lasts,
  and every Orbital holds a scan to reveal what attacks cloaked.
- `offense` (PRESSURE, COMMIT): a fight is sought. Every Orbital holds a scan
  for the army.
- `economy` (DEVELOP, RECOVER): Orbitals hold scans only once cloak was seen.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from sc2.position import Point2

from bot.attention import AttentionState, MapView
from bot.awareness import AwarenessState
from bot.ego.missions import CancelMode, MissionFeedback, MissionView
from bot.ego.planners import IntelPlan, Proposal, SensorTowerPlan
from bot.ego.strategy import StrategicIntent, StrategicPosture

from .missions.scout import KIND, OWNER, ScoutMission
from .policies import sensor_towers
from .policies.detection import Detection, DetectionConfig
from .policies.sensor_towers import MIN_BASES

if TYPE_CHECKING:
    from bot.body.engine import EngineResult

SCOUT_AT_WORKERS = 16
START_BY = 240.0
LAP_SECTORS = 8
_REOPENS = "workers_below_threshold"
THREAT = "threat"
OFFENSE = "offense"
ECONOMY = "economy"


class IntelPlanner:
    def __init__(self, detection_config: DetectionConfig | None = None) -> None:
        self.detection = Detection(detection_config)
        self.route: tuple[Point2, ...] = ()
        self.seen: set[int] = set()
        self.mission: ScoutMission | None = None
        self.finished: str | None = None
        self._opened = 0
        self._views: tuple[MissionView, ...] = ()
        self.sensor_coverage_enabled = False

    def views(self) -> tuple[MissionView, ...]:
        return self._views

    def plan(
        self,
        attention: AttentionState,
        awareness: AwarenessState,
        intent: StrategicIntent,
        feedback: EngineResult | None = None,
    ) -> IntelPlan:
        focus = intel_focus(intent.posture)
        views: list[MissionView] = []
        proposals = self._plan_scout(attention, feedback, views, hold=focus == THREAT)
        sensor_towers = self._plan_sensor_towers(attention)
        self._views = tuple(views)
        detection = self.detection.plan(attention, awareness, hold_scan=focus != ECONOMY)
        return IntelPlan(
            proposals=proposals,
            detection=detection,
            sensor_towers=sensor_towers,
            engineering_bay=detection.engineering_bay or sensor_towers.engineering_bay,
            focus=focus,
        )

    def _plan_sensor_towers(self, attention: AttentionState) -> SensorTowerPlan:
        # Once unlocked, coverage remains desired even after losing bases.
        self.sensor_coverage_enabled |= len(attention.bases) >= MIN_BASES
        if not self.sensor_coverage_enabled:
            return SensorTowerPlan(
                (),
                False,
                "fewer_than_four_bases",
                (
                    ("bases", float(len(attention.bases))),
                    ("required_bases", float(MIN_BASES)),
                ),
            )
        return sensor_towers.plan(attention)

    def _plan_scout(
        self,
        attention: AttentionState,
        feedback: EngineResult | None,
        views: list[MissionView],
        *,
        hold: bool = False,
    ) -> tuple[Proposal, ...]:
        """`hold`: no scout sets out while it holds; one already asked for goes on."""
        if self.finished is not None:
            return ()
        if not self.route:
            self.route = scouting_route(attention.map)
        now = attention.time
        self.seen.update(
            index
            for index, point in enumerate(self.route)
            if attention.is_visible(point)
        )
        mission = self.mission
        if mission is None:
            if len(self.seen) == len(self.route):
                self.finished = "route_seen"
                return ()
            if now >= START_BY:
                self.finished = "too_late"
                return ()
            if attention.workers < SCOUT_AT_WORKERS or hold:
                return ()
            self._opened += 1
            mission = ScoutMission(f"{OWNER}:{KIND}:{self._opened}", self.route, now)
            self.mission = mission
        else:
            mission.observe(attention)
            if mission.set_out is None and len(self.seen) < len(self.route):
                if now >= START_BY:
                    mission.request_cancel(CancelMode.IMMEDIATE, "too_late", now)
                elif attention.workers < SCOUT_AT_WORKERS:
                    mission.request_cancel(CancelMode.IMMEDIATE, _REOPENS, now)
        granted = MissionFeedback.of(feedback, mission.mission_id)
        proposals = mission.step(attention, frozenset(self.seen), granted)
        views.append(mission.view(granted, proposals))
        if not mission.active:
            self.mission = None
            if mission.reason != _REOPENS:
                self.finished = mission.reason
        return proposals


def intel_focus(posture: StrategicPosture) -> str:
    """What information matters most under a posture."""

    if posture is StrategicPosture.DEFEND:
        return THREAT
    if posture.offensive:
        return OFFENSE
    return ECONOMY


def scouting_route(map_view: MapView) -> tuple[Point2, ...]:
    start = map_view.enemy_start
    topology = map_view.topology
    region = (
        None
        if topology.enemy_start_region is None
        else topology.region(topology.enemy_start_region)
    )
    if region is None:
        return (start,)
    arrival = math.atan2(map_view.own_start.y - start.y, map_view.own_start.x - start.x)
    edge: dict[int, Point2] = {}
    for index in region.sample_indices:
        point = map_view.lattice[index]
        angle = (math.atan2(point.y - start.y, point.x - start.x) - arrival) % math.tau
        sector = int(angle / math.tau * LAP_SECTORS) % LAP_SECTORS
        best = edge.get(sector)
        if best is None or (point.distance_to(start), point.x, point.y) > (
            best.distance_to(start),
            best.x,
            best.y,
        ):
            edge[sector] = point
    return (start, *(edge[sector] for sector in sorted(edge)))

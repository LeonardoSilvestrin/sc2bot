"""Intel: scouting, detection and persistent information infrastructure.

What information matters most follows Strategy's posture, as this planner
reads it (`IntelPlan.focus`):

- `threat` (DEFEND): the threat is at home. No scout leaves while it lasts,
  and every Orbital holds a scan to reveal what attacks cloaked.
- `offense` (PRESSURE, COMMIT): a fight is sought. Every Orbital holds a scan
  for the army.
- `economy` (DEVELOP, RECOVER): Orbitals hold scans only once cloak was seen.

The early scout is the planner's one operation (`missions/early_scout.py`). The
planner opens it, ends it and decides when to send it hunting for a proxy --
which it asks Awareness, not the mission: a suspicion belongs to the layer that
reads the opening, the search to the one that walks the map. The same reading
tells the mission when its round is done: a scout only earns its place while
the opening is still unclear.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from sc2.position import Point2

from bot.attention import OPENING_WINDOW, AttentionState, MapView
from bot.awareness import AwarenessState, expectations_for
from bot.ego.missions import CancelMode, MissionFeedback, MissionView
from bot.ego.planners import EarlyScoutReport, IntelPlan, Proposal, SensorTowerPlan
from bot.ego.strategy import StrategicIntent, StrategicPosture

from .missions.early_scout import KIND, OWNER, EarlyScoutMission, ScoutWindow
from .policies import sensor_towers
from .policies.detection import Detection, DetectionConfig
from .policies.proxy import proxy_route
from .policies.sensor_towers import MIN_BASES

if TYPE_CHECKING:
    from bot.body.engine import EngineResult

SCOUT_AT_WORKERS = 16
START_BY = 240.0
LAP_SECTORS = 8
# The opening read that sends the scout looking for a proxy, and the least it
# must be worth to be acted on.
PROXY_SEARCH_AT = 0.55
PROXY_CONFIDENCE_AT = 0.3
_REOPENS = "workers_below_threshold"
THREAT = "threat"
OFFENSE = "offense"
ECONOMY = "economy"


class IntelPlanner:
    def __init__(self, detection_config: DetectionConfig | None = None) -> None:
        self.detection = Detection(detection_config)
        self.route: tuple[Point2, ...] = ()
        self.proxy_route: tuple[Point2, ...] = ()
        self.exits: tuple[Point2, ...] = ()
        self.seen: set[int] = set()
        self.mission: EarlyScoutMission | None = None
        self.finished: str | None = None
        # When the proxy search was ordered; None while none was.
        self.proxy_search: float | None = None
        self._opened = 0
        self._views: tuple[MissionView, ...] = ()
        self.sensor_coverage_enabled = False
        self._map: MapView | None = None

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
        scout: list[EarlyScoutReport] = []
        proposals = self._plan_scout(
            attention, awareness, feedback, views, scout, hold=focus == THREAT
        )
        sensor_towers = self._plan_sensor_towers(attention)
        self._views = tuple(views)
        detection = self.detection.plan(attention, awareness, hold_scan=focus != ECONOMY)
        return IntelPlan(
            proposals=proposals,
            detection=detection,
            sensor_towers=sensor_towers,
            engineering_bay=detection.engineering_bay or sensor_towers.engineering_bay,
            focus=focus,
            scout=scout[0] if scout else None,
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
        awareness: AwarenessState,
        feedback: EngineResult | None,
        views: list[MissionView],
        reports: list[EarlyScoutReport],
        *,
        hold: bool = False,
    ) -> tuple[Proposal, ...]:
        """`hold`: no scout sets out while it holds; one already asked for goes on."""
        if self.finished is not None:
            return ()
        if self._map is not attention.map:
            self._map = attention.map
            self.route = scouting_route(attention.map)
            self.proxy_route = proxy_route(attention.map)
            self.exits = enemy_exits(attention.map)
            if self.mission is not None:
                self.mission.refresh_paths(self.proxy_route, self.exits, attention.time)
        now = attention.time
        self.seen.update(
            index for index, point in enumerate(self.route) if attention.is_visible(point)
        )
        mission = self.mission
        if mission is None:
            if now >= START_BY:
                self.finished = "too_late"
                return ()
            if attention.workers < SCOUT_AT_WORKERS or hold:
                return ()
            self._opened += 1
            mission = EarlyScoutMission(
                f"{OWNER}:{KIND}:{self._opened}",
                self.route,
                now,
                natural=attention.map.enemy_natural,
                third=attention.map.enemy_third,
                proxy_route=self.proxy_route,
                watchpoints=self.exits,
                window=scout_window(attention),
            )
            self.mission = mission
        else:
            mission.observe(attention)
            if mission.set_out is None:
                if now >= START_BY:
                    mission.request_cancel(CancelMode.IMMEDIATE, "too_late", now)
                elif attention.workers < SCOUT_AT_WORKERS:
                    mission.request_cancel(CancelMode.IMMEDIATE, _REOPENS, now)
        self._direct_proxy_search(mission, attention, awareness)
        granted = MissionFeedback.of(feedback, mission.mission_id)
        # The mission reads the opening to know whether its round still has
        # anything to add; the reading itself is Awareness'.
        proposals = mission.step(attention, frozenset(self.seen), granted, awareness.opening)
        views.append(mission.view(granted, proposals))
        reports.append(mission.report())
        if not mission.active:
            self.mission = None
            if mission.reason != _REOPENS:
                self.finished = mission.reason
        return proposals

    def _direct_proxy_search(
        self, mission: EarlyScoutMission, attention: AttentionState, awareness: AwarenessState
    ) -> None:
        """A proxy the opening read believes in is worth looking for, once."""

        if self.proxy_search is not None:
            return
        opening = awareness.opening
        if opening.proxy < PROXY_SEARCH_AT or opening.confidence < PROXY_CONFIDENCE_AT:
            return
        if mission.search_proxy("opening_reads_proxy", attention.time):
            self.proxy_search = attention.time


def scout_window(attention: AttentionState) -> ScoutWindow:
    """The scout's clock, by the race it is scouting: a third that says
    something about a Zerg opening says it long before a Terran one.

    Nothing is recorded past `OPENING_WINDOW`, so there is nothing left to
    learn there either: that is where the operation stops for every race."""

    default = ScoutWindow()
    third_late = expectations_for(attention.enemy_race).third_late
    return replace(
        default,
        third_until=min(third_late, OPENING_WINDOW),
        until=OPENING_WINDOW,
    )


def intel_focus(posture: StrategicPosture) -> str:
    """What information matters most under a posture."""

    if posture is StrategicPosture.DEFEND:
        return THREAT
    if posture.offensive:
        return OFFENSE
    return ECONOMY


def enemy_exits(map_view: MapView, limit: int = 2) -> tuple[Point2, ...]:
    """The ways out of the enemy main: the open passages of its region, widest
    first. What leaves their base crosses one of these, so they are worth
    coming back to while the opening lasts. A passage rocks or a mineral wall
    still hold is not a way out and is not watched."""

    topology = map_view.topology
    region = topology.enemy_start_region
    if region is None:
        return ()
    wanted = {passage_id for _, passage_id in topology.neighbours(region, open_only=True)}
    passages = [passage for passage in topology.open_passages() if passage.passage_id in wanted]
    passages.sort(key=lambda passage: (-(passage.width or 0.0), passage.passage_id))
    return tuple(passage.position for passage in passages[:limit])


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

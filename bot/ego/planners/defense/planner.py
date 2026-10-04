"""DefensePlanner: one DefendAreaMission per threat incident, and one
RushDefenseMission while a rush is on.

Awareness groups the attackers in reach of our bases into incidents and keeps
an incident's id while its attackers come and go. The planner opens a mission
for every incident it has none for, hands each mission this frame's report of
its incident, and lets a mission whose incident Awareness no longer reports
complete. It never asks one to end: while an attacker is in reach, defending
is what Strategy wants most. The intent reaches the missions: under DEFEND
they answer with a larger budget.

A rush is answered on top of that, by fortifying: when the rush reading
(`policies/rush.py`) reaches `open_at`, the planner opens a rush defense at
the base the rush will hit -- the natural once a townhall stands there, else
the main -- and the mission wants a Bunker there, fills it and repairs it. One
at a time: a failed one (its base lost) is followed by a new one where the
bases now are, if the rush still reads.

The planner keeps the open missions, by incident, the rush defense, and the
counts that number them: an incident id Awareness reuses later is a new
mission.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from bot.attention import AttentionState
from bot.awareness import AwarenessState
from bot.ego.planners import (
    DefensePlan,
    FortificationPlan,
    MissionFeedback,
    MissionView,
    Proposal,
)
from bot.ego.strategy import StrategicIntent

from .missions import rush_defense
from .missions.defend_area import KIND, OWNER, DefendAreaMission
from .missions.rush_defense import RushDefenseMission, RushStep
from .policies.rush import RushConfig, RushReading, bunker_site, read_rush

if TYPE_CHECKING:
    from bot.body.engine import EngineResult


class DefensePlanner:
    def __init__(self, rush_config: RushConfig | None = None) -> None:
        self.rush_config = rush_config or RushConfig()
        # The open missions, by incident id.
        self._missions: dict[str, DefendAreaMission] = {}
        self._opened = 0
        self.rush_defense: RushDefenseMission | None = None
        self._rushes = 0
        # This frame's rush reading.
        self.rush = RushReading()
        self._views: tuple[MissionView, ...] = ()

    @property
    def missions(self) -> tuple[DefendAreaMission, ...]:
        """The open missions, in the order their incidents were reported."""

        return tuple(self._missions.values())

    def views(self) -> tuple[MissionView, ...]:
        """The missions this frame's `plan` governed, as they left it."""

        return self._views

    def plan(
        self,
        attention: AttentionState,
        awareness: AwarenessState,
        intent: StrategicIntent,
        feedback: EngineResult | None = None,
    ) -> DefensePlan:
        """`feedback`: the last `EngineResult`, or None before the first."""

        now = attention.time
        proposals: list[Proposal] = []
        views: list[MissionView] = []
        reported = {incident.incident_id for incident in awareness.incidents}
        stepped: dict[str, DefendAreaMission] = {}
        for incident in awareness.incidents:
            mission = self._missions.get(incident.incident_id)
            if mission is None:
                self._opened += 1
                mission = DefendAreaMission(
                    f"{OWNER}:{KIND}:{self._opened}", incident.incident_id, now
                )
            granted = MissionFeedback.of(feedback, mission.mission_id)
            made = mission.step(incident, intent, granted)
            proposals.extend(made)
            views.append(mission.view(granted, made))
            if mission.active:
                stepped[incident.incident_id] = mission
        for incident_id, mission in self._missions.items():
            if incident_id in reported:
                continue
            granted = MissionFeedback.of(feedback, mission.mission_id)
            views.append(mission.view(granted, mission.step(None, intent, granted)))
        self._missions = stepped
        fortification = self._plan_rush(attention, awareness, feedback, proposals, views)
        self._views = tuple(views)
        return DefensePlan(proposals=tuple(proposals), fortification=fortification)

    def _plan_rush(
        self,
        attention: AttentionState,
        awareness: AwarenessState,
        feedback: EngineResult | None,
        proposals: list[Proposal],
        views: list[MissionView],
    ) -> FortificationPlan:
        config = self.rush_config
        reading = read_rush(awareness)
        self.rush = reading
        unload: tuple[int, ...] = ()
        reason = "no_rush"
        mission = self.rush_defense
        if mission is not None:
            step = self._step_rush(mission, attention, awareness, feedback, proposals, views)
            if mission.active:
                return self._fortification(step, mission.reason, reading)
            # A Bunker left behind lets its garrison out even while a new
            # defense opens elsewhere in the same frame.
            unload, reason = step.unload, mission.reason
            self.rush_defense = None
        site = bunker_site(attention) if reading.level >= config.open_at else None
        if site is None:
            return FortificationPlan(unload=unload, reason=reason, inputs=reading.inputs)
        self._rushes += 1
        mission = RushDefenseMission(
            f"{rush_defense.OWNER}:{rush_defense.KIND}:{self._rushes}",
            site,
            attention.time,
            "rush_expected" if reading.expected >= reading.present else "rush_present",
        )
        step = self._step_rush(mission, attention, awareness, feedback, proposals, views)
        self.rush_defense = mission if mission.active else None
        return self._fortification(
            replace(step, unload=unload + step.unload), mission.reason, reading
        )

    def _step_rush(
        self,
        mission: RushDefenseMission,
        attention: AttentionState,
        awareness: AwarenessState,
        feedback: EngineResult | None,
        proposals: list[Proposal],
        views: list[MissionView],
    ) -> RushStep:
        step = mission.step(attention, awareness, self.rush, self.rush_config)
        proposals.extend(step.proposals)
        views.append(mission.view(MissionFeedback.of(feedback, mission.mission_id), step.proposals))
        return step

    @staticmethod
    def _fortification(step: RushStep, reason: str, reading: RushReading) -> FortificationPlan:
        return FortificationPlan(
            bunkers=() if step.bunker is None else (step.bunker,),
            unload=step.unload,
            reason=reason,
            inputs=reading.inputs,
        )

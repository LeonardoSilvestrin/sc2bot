"""DefensePlanner: one DefendAreaMission per threat incident.

Awareness groups the attackers in reach of our bases into incidents and keeps
an incident's id while its attackers come and go. The planner opens a mission
for every incident it has none for, hands each mission this frame's report of
its incident, and lets a mission whose incident Awareness no longer reports
complete. It never asks one to end: while an attacker is in reach, defending
is what Strategy wants most. The intent reaches the missions: under DEFEND
they answer with a larger budget.

The planner keeps only the open missions, by incident, and the count that
numbers them: an incident id Awareness reuses later is a new mission.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.attention import AttentionState
from bot.awareness import AwarenessState
from bot.ego.missions import MissionFeedback, MissionView
from bot.ego.planners import Proposal
from bot.ego.strategy import StrategicIntent

from .missions.defend_area import KIND, OWNER, DefendAreaMission

if TYPE_CHECKING:
    from bot.body.engine import EngineResult


class DefensePlanner:
    def __init__(self) -> None:
        # The open missions, by incident id.
        self._missions: dict[str, DefendAreaMission] = {}
        self._opened = 0
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
    ) -> tuple[Proposal, ...]:
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
        self._views = tuple(views)
        return tuple(proposals)

"""DefendAreaMission: answer one threat incident until it is over.

However many bases the incident touches, it gets one budget: COVER_MARGIN
times its power. The budget is split by what the attackers are -- the part
that flies can only be answered by units that shoot up, the part on the
ground by units that shoot down -- so the parts add up to the budget and
never repeat it. Each part is a proposal that asks the Engine for power, not
a head count, and the Engine hands out the nearest compatible units first:
cover already on the spot answers before anything is pulled from elsewhere.
The air part ranks first (its id sorts first at equal priority), since fewer
units shoot up. Both parts share the incident's id as their `demand_id`, and
their ids follow the incident, so the Engine keeps the same defenders while
the incident's attackers come and go.

Priority is the incident's threat on the base it presses hardest, raised by
how much Strategy wants defense, so it is positive exactly while an attacker
is in reach -- always above the offense (0) and the ArmyFallback fallback (-1).

The mission is sized again every frame from the incident Awareness reports;
it completes once Awareness reports the incident no more.
"""

from __future__ import annotations

from collections.abc import Sequence

from bot.awareness import ThreatIncident
from bot.ego.missions import (
    CancelMode,
    Lifecycle,
    MissionFeedback,
    MissionStatus,
    MissionView,
)
from bot.ego.planners import Command, Domain, Proposal
from bot.ego.strategy import StrategyState

OWNER = "defense"
KIND = "defend_area"
# Answer an attack with this much more power than it brings.
COVER_MARGIN = 1.5
# The only phase: the incident is in reach and answered.
DEFENDING = "DEFENDING"


class DefendAreaMission:
    def __init__(self, mission_id: str, incident_id: str, now: float) -> None:
        self.lifecycle = Lifecycle(mission_id)
        self.incident_id = incident_id
        self.phase = DEFENDING
        self.since = now
        self.reason = "attackers_in_reach"

    @property
    def mission_id(self) -> str:
        return self.lifecycle.mission_id

    @property
    def status(self) -> MissionStatus:
        return self.lifecycle.status

    @property
    def active(self) -> bool:
        return self.lifecycle.active

    def request_cancel(self, mode: CancelMode, reason: str, now: float) -> None:
        self.lifecycle.request_cancel(mode, reason, now)

    def step(
        self,
        incident: ThreatIncident | None,
        strategy: StrategyState,
        feedback: MissionFeedback,
    ) -> tuple[Proposal, ...]:
        """`incident`: this frame's report of the incident; None once it is over."""

        if not self.active:
            return ()
        now = strategy.time
        cancel = self.lifecycle.cancel
        if cancel is not None:
            # Defenders fight where they stand: nothing to walk back from.
            return self._end(MissionStatus.CANCELLED, cancel.reason, now)
        if incident is None:
            return self._end(MissionStatus.COMPLETED, "incident_over", now)
        priority = incident.threat * (0.5 + 0.5 * strategy.defense)
        budget = COVER_MARGIN * incident.power
        proposals: list[Proposal] = []
        for domain, power in (
            (Domain.AIR, incident.air_power),
            (Domain.GROUND, incident.ground_power),
        ):
            if power <= 0.0:
                continue
            part = domain.value.lower()
            proposals.append(
                Proposal(
                    proposal_id=f"{OWNER}:{incident.incident_id}:{part}",
                    owner=OWNER,
                    priority=priority,
                    command=Command.ATTACK,
                    target=incident.center,
                    reason=f"{part}_attackers_in_reach",
                    minimum_power=COVER_MARGIN * power,
                    must_attack=domain,
                    demand_id=incident.incident_id,
                    inputs=(
                        ("threat", incident.threat),
                        ("pressure", incident.pressure),
                        ("incident_power", incident.power),
                        ("part_power", power),
                        ("budget", budget),
                        ("confidence", incident.confidence),
                        ("contacts", float(len(incident.contacts))),
                        ("affected_bases", float(len(incident.affected_bases))),
                        ("strategy_defense", strategy.defense),
                    ),
                    mission_id=self.mission_id,
                )
            )
        return tuple(proposals)

    def view(self, feedback: MissionFeedback, proposals: Sequence[Proposal]) -> MissionView:
        return MissionView(
            mission_id=self.mission_id,
            owner=OWNER,
            kind=KIND,
            status=self.status,
            phase=self.phase,
            since=self.since,
            reason=self.reason,
            cancel=self.lifecycle.cancel,
            proposals=tuple(proposal.proposal_id for proposal in proposals),
            granted_units=len(feedback.tags),
            granted_power=feedback.power,
        )

    def _end(self, status: MissionStatus, reason: str, now: float) -> tuple[Proposal, ...]:
        self.since, self.reason = now, reason
        self.lifecycle.end(status)
        return ()

"""Defense: one coordinated demand per threat incident.

Awareness groups the attackers in reach of our bases into incidents. However
many bases an incident touches, it gets one budget: COVER_MARGIN times its
power. The budget is split by what the attackers are -- the part that flies can
only be answered by units that shoot up, the part on the ground by units that
shoot down -- so the parts add up to the budget and never repeat it. Each part
asks the Engine for power, not a head count, and the Engine hands out the
nearest compatible units first: cover already on the spot answers before
anything is pulled from elsewhere. The air part ranks first (its id sorts
first at equal priority), since fewer units shoot up.

Priority is the incident's threat on the base it presses hardest, raised by how
much Strategy wants defense, so it is positive exactly while an attacker is in
reach -- always above the offense (0) and the CoreArmy fallback (-1).
"""

from __future__ import annotations

from bot.attention import AttentionState
from bot.awareness import AwarenessState
from bot.ego.planners import Command, Domain, Proposal
from bot.ego.strategy import StrategyState

OWNER = "defense"
# Answer an attack with this much more power than it brings.
COVER_MARGIN = 1.5


def plan(
    attention: AttentionState, awareness: AwarenessState, strategy: StrategyState
) -> tuple[Proposal, ...]:
    proposals: list[Proposal] = []
    for incident in awareness.incidents:
        priority = incident.threat * (0.5 + 0.5 * strategy.defense)
        budget = COVER_MARGIN * incident.power
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
                )
            )
    return tuple(proposals)

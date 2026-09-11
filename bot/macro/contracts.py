"""The contract a macro planner keeps.

A behavior planner (`bot.behavior.contracts.BehaviorPlanner`) proposes
missions: work for units already on the map. A spend planner proposes
purchases: one increment of a unit, structure, add-on, upgrade or base, paid
for out of the bank. Both read the same Attention and Awareness; what they
return goes to different controllers, and nothing on this side names a unit
tag, a mission, a squad or a lease.

The discipline is a behavior's, minus ownership. An assessment only
describes (`production/army_demand.py`, `construction/capacity.py`'s
`assess_capacity`), a proposer only argues for one step, and
`EconomyController` alone admits, reserves and dispatches.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from bot.engine.economy.models import EconomicProposal
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot


@runtime_checkable
class SpendPlanner(Protocol):
    """Turns Attention + Awareness into economic proposals.

    It never checks affordability -- the bank is the controller's to
    arbitrate -- and never commands anything: a proposal argues for one
    purchase, it is not the purchase.
    """

    planner_id: str

    def propose(
        self, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> tuple[EconomicProposal, ...]:
        ...


__all__ = ["SpendPlanner"]

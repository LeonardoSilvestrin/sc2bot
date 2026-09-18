"""CoreArmy: the fallback owner of every army unit no one else needs.

Always proposed, always last -- below Defense and the offense: it asks for
every free army unit and holds them at the rally point Strategy chose.
"""

from __future__ import annotations

from bot.attention import AttentionState
from bot.awareness import AwarenessState
from bot.ego.planners import Command, Proposal
from bot.ego.strategy import StrategyState

OWNER = "core_army"
FALLBACK_PRIORITY = -1.0


def plan(
    attention: AttentionState, awareness: AwarenessState, strategy: StrategyState
) -> tuple[Proposal, ...]:
    return (
        Proposal(
            proposal_id=OWNER,
            owner=OWNER,
            priority=FALLBACK_PRIORITY,
            command=Command.HOLD,
            target=strategy.rally,
            reason=f"hold_rally_{strategy.objective.value.lower()}",
            inputs=(("risk", strategy.risk), ("danger", awareness.danger)),
        ),
    )

"""ArmyFallbackPlanner: the owner of every army unit no one else needs.

Always proposed, always last -- below Defense and the offense: it asks for
every free army unit and holds them at the rally point Strategy chose. It is
no strategic reserve: it gets whatever the planners above left. No operation
of its own, so no missions.

Its proposal keeps the id and owner `core_army`, its name before the rename:
the logs, the viewer and every bench so far know it by that name.
"""

from __future__ import annotations

from bot.attention import AttentionState
from bot.awareness import AwarenessState
from bot.ego.planners import Command, Proposal
from bot.ego.strategy import StrategyState

OWNER = "core_army"
FALLBACK_PRIORITY = -1.0


class ArmyFallbackPlanner:
    def plan(
        self, attention: AttentionState, awareness: AwarenessState, strategy: StrategyState
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

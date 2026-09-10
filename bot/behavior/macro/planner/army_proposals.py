from __future__ import annotations

from bot.engine.economy.models import EconomicActionKind, EconomicProposal
from bot.world.awareness import MacroPosture

from ..macro_config import MacroPlannerConfig
from .army_demand import ArmyDemand
from .proposal_helpers import build_proposal


def propose_army(
    config: MacroPlannerConfig,
    planner_id: str,
    demand: ArmyDemand,
    posture: MacroPosture,
    now: float,
) -> tuple[EconomicProposal, ...]:
    """Ask for one more of every unit the army still owes.

    Spawn decides *which unit* is useful now; it never decides to build a
    Barracks (see ``production_proposals``) and never spends anything -- the
    economy controller admits or rejects each of these one at a time.
    """

    if demand.supply_debt <= 0.0:
        return ()

    priority_offset = {
        goal.unit_type: goal.priority_offset for goal in config.goals.army
    }
    return tuple(
        build_proposal(
            planner_id=planner_id,
            kind=EconomicActionKind.PRODUCE_UNIT,
            category="army",
            target=unit.unit_type.name,
            current_count=unit.total,
            desired_count=unit.desired,
            priority=config.priority_for(
                "army", posture, offset=priority_offset[unit.unit_type]
            ),
            reason="army_supply_below_target_for_this_composition_member",
            cost=unit.cost,
            now=now,
        )
        for unit in demand.units
        if unit.buildable_shortfall > 0
    )

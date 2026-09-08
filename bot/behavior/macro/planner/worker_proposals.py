from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId

from bot.engine.economy.models import EconomicActionKind, EconomicProposal
from bot.world.attention import EconomyFacts
from bot.world.awareness import MacroPosture

from ..macro_config import MacroPlannerConfig
from .proposal_helpers import build_proposal, saturation_target


def propose_worker(
    config: MacroPlannerConfig,
    planner_id: str,
    economy: EconomyFacts,
    posture: MacroPosture,
    now: float,
) -> EconomicProposal | None:
    desired = _desired_workers(config, economy)
    if economy.workers.total >= desired:
        return None
    return build_proposal(
        planner_id=planner_id,
        kind=EconomicActionKind.PRODUCE_WORKER,
        category="worker",
        target=UnitTypeId.SCV.name,
        target_count=desired,
        priority=config.priority_for("worker", posture),
        reason="worker_count_below_current_saturation_target",
        cost=config.worker_cost,
        now=now,
    )


def _desired_workers(config: MacroPlannerConfig, economy: EconomyFacts) -> int:
    goals = config.goals
    saturation = saturation_target(economy, goals.workers_per_townhall)
    return min(goals.max_workers, saturation)

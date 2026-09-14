"""Economy: the workers mine, and the economy plan runs as Ares macro behaviors.

Mining always runs; a worker the Engine released goes back to the GATHERING
role, so Mining takes it again. The macro plan runs only once the opening is
over.
"""

from __future__ import annotations

from ares.behaviors.macro import (
    AutoSupply,
    BuildWorkers,
    ExpansionController,
    GasBuildingController,
    MacroPlan,
    Mining,
    ProductionController,
    SpawnController,
)
from ares.consts import UnitRole

from bot.attention import AttentionState
from bot.body.engine import EngineResult
from bot.ego.planners import EconomyPlan


def release_workers(bot, attention: AttentionState, result: EngineResult) -> None:
    """A worker no proposal holds any more goes back to mining."""

    workers = {unit.tag for unit in attention.own_units if unit.is_worker}
    for tag in result.released:
        if tag in workers:
            bot.mediator.assign_role(tag=tag, role=UnitRole.GATHERING)


def execute(bot, plan: EconomyPlan) -> None:
    bot.register_behavior(Mining())
    if not plan.active:
        return
    composition = {
        unit_type: {"proportion": proportion, "priority": priority}
        for unit_type, proportion, priority in plan.composition
    }
    macro = MacroPlan()
    macro.add(AutoSupply(base_location=bot.start_location))
    macro.add(BuildWorkers(to_count=plan.workers))
    macro.add(GasBuildingController(to_count=plan.gas))
    if plan.expand:
        macro.add(ExpansionController(to_count=plan.bases))
    macro.add(SpawnController(composition, freeflow_mode=plan.freeflow))
    macro.add(ProductionController(composition, base_location=bot.start_location))
    bot.register_behavior(macro)

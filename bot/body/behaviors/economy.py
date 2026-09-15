"""Economy: the workers mine, and the economy plan runs as Ares macro behaviors.

Mining always runs; a worker the Engine released goes back to the GATHERING
role, so Mining takes it again. The macro plan runs only once the opening is
over.

Ares' SpawnController skips a unit type once its share of the army is met,
counting what is in production. When every type of the composition is met at
once -- counts an exact multiple of the proportions, like 11 Marines, 4
Marauders, 3 Siege Tanks and 2 Medivacs for 0.55/0.2/0.15/0.1 -- it trains
nothing at all, and the army stops growing until a unit dies. That frame it
spends freely instead: whatever it trains takes the counts off the multiple.
"""

from __future__ import annotations

from dataclasses import dataclass

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
from sc2.ids.unit_typeid import UnitTypeId

from bot.attention import AttentionState
from bot.body.engine import EngineResult
from bot.ego.planners import EconomyPlan

# SpawnController's guard against an empty army in its share test.
_EMPTY_ARMY = 1e-16


@dataclass(frozen=True, slots=True)
class SpawnMode:
    """How the plan's composition went to Ares' SpawnController this frame."""

    freeflow: bool
    # plan_inactive, plan_freeflow, composition_met or composition_short.
    reason: str
    # (unit type, count) as SpawnController counts them: aliases and units in
    # production included. Empty while the plan is inactive.
    counts: tuple[tuple[UnitTypeId, int], ...] = ()


def release_workers(bot, attention: AttentionState, result: EngineResult) -> None:
    """A worker no proposal holds any more goes back to mining."""

    workers = {unit.tag for unit in attention.own_units if unit.is_worker}
    for tag in result.released:
        if tag in workers:
            bot.mediator.assign_role(tag=tag, role=UnitRole.GATHERING)


def execute(bot, plan: EconomyPlan) -> SpawnMode:
    bot.register_behavior(Mining())
    if not plan.active:
        return SpawnMode(freeflow=False, reason="plan_inactive")
    spawn = spawn_mode(bot, plan)
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
    macro.add(SpawnController(composition, freeflow_mode=spawn.freeflow))
    macro.add(ProductionController(composition, base_location=bot.start_location))
    bot.register_behavior(macro)
    return spawn


def spawn_mode(bot, plan: EconomyPlan) -> SpawnMode:
    counts = tuple(
        (unit_type, int(bot.mediator.get_own_unit_count(unit_type_id=unit_type)))
        for unit_type, _, _ in plan.composition
    )
    if plan.freeflow:
        return SpawnMode(freeflow=True, reason="plan_freeflow", counts=counts)
    total = sum(count for _, count in counts)
    # SpawnController's own test, type by type: a type whose share is met is skipped.
    met = bool(counts) and all(
        count / (total + _EMPTY_ARMY) >= proportion
        for (_, count), (_, proportion, _) in zip(counts, plan.composition, strict=True)
    )
    if met:
        return SpawnMode(freeflow=True, reason="composition_met", counts=counts)
    return SpawnMode(freeflow=False, reason="composition_short", counts=counts)

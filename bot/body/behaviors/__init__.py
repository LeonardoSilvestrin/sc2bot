"""Local execution of grants and direct plans; see docs/architecture.md.

Unit commands use only granted actors. Direct plans may select equivalent
structures and builders locally. Execution preserves the received intent.
Scans precede MULEs; their actual actor tags prevent conflicting orders.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from bot.attention import AttentionState
from bot.body.engine import EngineResult
from bot.ego.planners import (
    Command,
    EconomyPlan,
    IntelPlan,
    StructurePlan,
)

from . import (
    attack,
    detection,
    economy,
    hold,
    intel,
    retreat,
    scout,
    sensor_towers,
    structure_control,
)

# The behavior that carries out each command with the units granted to it,
# whichever planner proposed it.
# A behavior may return the local reactions it took.
BY_COMMAND: dict[Command, Callable[..., attack.MicroReport | None]] = {
    Command.ATTACK: attack.execute,
    Command.HOLD: hold.execute,
    Command.SCOUT: scout.execute,
    Command.RETREAT: retreat.execute,
}


@dataclass(frozen=True, slots=True)
class BodyReport:
    spawn: economy.SpawnMode
    micro: attack.MicroReport
    detection: detection.DetectionReport = detection.DetectionReport()
    sensor_towers: sensor_towers.SensorTowerReport = sensor_towers.SensorTowerReport()
    infrastructure: tuple[str, ...] = ()


def execute(
    bot,
    attention: AttentionState,
    result: EngineResult,
    economy_plan: EconomyPlan,
    structures: StructurePlan,
    intel_plan: IntelPlan | None = None,
) -> BodyReport:
    economy.release_workers(bot, attention, result)
    micro = command_units(bot, result)
    detected = detection.DetectionReport()
    reserve = 0.0
    if intel_plan is not None:
        detected = detection.execute(bot, intel_plan.detection)
        reserve = intel_plan.detection.energy_reserve
    infrastructure: tuple[str, ...] = ()
    towers = sensor_towers.SensorTowerReport()
    if intel_plan is not None:
        infrastructure = intel.execute(bot, intel_plan)
        towers = sensor_towers.execute(bot, intel_plan.sensor_towers)
    busy = frozenset(() if detected.scanned_by is None else (detected.scanned_by,))
    spawn = economy.execute(
        bot,
        economy_plan,
        energy_reserve=reserve,
        busy=busy,
        lifting=frozenset(structures.lift),
    )
    structure_control.execute(bot, structures)
    return BodyReport(spawn, micro, detected, towers, infrastructure)


def command_units(bot, result: EngineResult) -> attack.MicroReport:
    """Hand each grant's living units to the behavior for its command."""

    units = bot.unit_tag_dict
    report = attack.MicroReport()
    for grant in result.grants:
        granted = [units[tag] for tag in grant.tags if tag in units]
        if granted:
            reacted = BY_COMMAND[grant.proposal.command](bot, granted, grant.proposal)
            if reacted is not None:
                report = report.merge(reacted)
    return report

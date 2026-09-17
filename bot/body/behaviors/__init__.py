"""BEHAVIORS: how the Body carries out what the Engine granted.

`execute` runs once per frame, right after the Engine, in this order: workers
the Engine released go back to mining, each grant is carried out by the
behavior for its command, then the economy and structure plans run. Ares runs
a behavior as soon as it is registered, so the order is the order of effects.
A behavior never picks its units; it commands only the ones it was granted.
`execute` reports, for the log, how the army composition went to Ares'
SpawnController and which local reactions the fighting behaviors took.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from bot.attention import AttentionState
from bot.body.engine import EngineResult
from bot.ego.planners import Command, EconomyPlan, StructurePlan

from . import attack, core_army, economy, retreat, scout, structure_control

# The behavior that carries out each command with the units granted to it,
# whichever planner proposed it.
# A behavior may return the local reactions it took.
BY_COMMAND: dict[Command, Callable[..., attack.MicroReport | None]] = {
    Command.ATTACK: attack.execute,
    Command.HOLD: core_army.execute,
    Command.SCOUT: scout.execute,
    Command.RETREAT: retreat.execute,
}


@dataclass(frozen=True, slots=True)
class BodyReport:
    spawn: economy.SpawnMode
    micro: attack.MicroReport


def execute(
    bot,
    attention: AttentionState,
    result: EngineResult,
    economy_plan: EconomyPlan,
    structures: StructurePlan,
) -> BodyReport:
    economy.release_workers(bot, attention, result)
    micro = command_units(bot, result)
    spawn = economy.execute(bot, economy_plan)
    structure_control.execute(bot, structures)
    return BodyReport(spawn=spawn, micro=micro)


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

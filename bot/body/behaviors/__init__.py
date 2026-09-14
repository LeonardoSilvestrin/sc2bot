"""BEHAVIORS: how the Body carries out what the Engine granted.

`execute` runs once per frame, right after the Engine, in this order: workers
the Engine released go back to mining, each grant is carried out by the
behavior for its command, then the economy and structure plans run. Ares runs
a behavior as soon as it is registered, so the order is the order of effects.
A behavior never picks its units; it commands only the ones it was granted.
"""

from __future__ import annotations

from collections.abc import Callable

from bot.attention import AttentionState
from bot.body.engine import EngineResult
from bot.ego.planners import Command, EconomyPlan, StructurePlan

from . import core_army, defense, economy, scout, structure_control

# The behavior that carries out each command with the units granted to it.
BY_COMMAND: dict[Command, Callable[..., None]] = {
    Command.ATTACK: defense.execute,
    Command.HOLD: core_army.execute,
    Command.SCOUT: scout.execute,
}


def execute(
    bot,
    attention: AttentionState,
    result: EngineResult,
    economy_plan: EconomyPlan,
    structures: StructurePlan,
) -> None:
    economy.release_workers(bot, attention, result)
    command_units(bot, result)
    economy.execute(bot, economy_plan)
    structure_control.execute(bot, structures)


def command_units(bot, result: EngineResult) -> None:
    """Hand each grant's living units to the behavior for its command."""

    units = bot.unit_tag_dict
    for grant in result.grants:
        granted = [units[tag] for tag in grant.tags if tag in units]
        if granted:
            BY_COMMAND[grant.proposal.command](bot, granted, grant.proposal)

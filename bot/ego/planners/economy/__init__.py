"""Economy: what the bot spends its resources on after the opening.

A resource planner: it asks for no unit, only for what Ares' macro behaviors
should buy. Three questions, one module each:

- `investment`: how much -- workers, bases, gas, production ceiling, and when
  the macro plan takes over from the opening.
- `styles`: what -- the army style chosen for the game, with its composition,
  upgrades and add-ons.
- `composition`: what now -- the style's composition reweighted by what each
  unit is worth against the enemy army Awareness believes in.

`plan` joins them into the `EconomyPlan` the Body's economy behavior runs.
After the opening, Command Centers become Orbital Commands and every Orbital's
energy goes to MULEs. While stabilizing, every resource goes to the army: no
upgrade and no add-on for throughput.
"""

from __future__ import annotations

from collections.abc import Iterable

from sc2.ids.unit_typeid import UnitTypeId

from bot.attention import AttentionState
from bot.ego.planners import EconomyPlan
from bot.ego.strategy import StrategyState

from . import composition, investment, styles
from .styles import BIO, ArmyStyle


def plan(
    attention: AttentionState,
    strategy: StrategyState,
    army: ArmyStyle = BIO,
    enemy: Iterable[tuple[UnitTypeId, float]] = (),
) -> EconomyPlan:
    """`enemy` is the enemy army believed in, as power by unit type."""

    spend = investment.plan(attention, strategy)
    enemy = tuple(enemy)
    mix = composition.mix(army, enemy)
    upgrades_done = sum(item in attention.upgrades for item in army.upgrades)
    invests = spend.active and not spend.stabilizing
    return EconomyPlan(
        active=spend.active,
        workers=spend.workers,
        gas=spend.gas,
        bases=spend.bases,
        expand=spend.expand,
        freeflow=spend.stabilizing,
        composition=mix,
        reason=spend.reason,
        inputs=(
            *spend.inputs,
            ("upgrades_done", float(upgrades_done)),
            ("techlab_reserve", float(army.techlab_reserve)),
            ("enemy_seen_power", sum(power for _, power in enemy)),
        ),
        upgrades=army.upgrades if invests else (),
        orbitals=spend.active,
        mules=spend.active,
        interrupt_opening=spend.interrupt_opening,
        max_production=spend.max_production,
        # A Reactor is an investment in throughput: while stabilizing, every
        # resource goes to the army instead, as with the upgrades.
        reactors=invests,
        reactor_on=army.reactor_on,
        reactor_share=composition.reactor_share(mix, army.reactor_on),
        techlab_reserve=army.techlab_reserve,
        army=army.name,
    )


__all__ = ["ArmyStyle", "composition", "investment", "plan", "styles"]

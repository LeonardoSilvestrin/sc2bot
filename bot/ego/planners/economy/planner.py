"""The economy planner: `plan` joins the investment and composition policies
and the chosen style into the `EconomyPlan` the Body's economy behavior runs.
After the opening, Command Centers become Orbital Commands and every Orbital's
energy goes to MULEs. While stabilizing, every resource goes to the army: no
upgrade and no add-on for throughput.
"""

from __future__ import annotations

from collections.abc import Iterable

from sc2.ids.unit_typeid import UnitTypeId

from bot.attention import AttentionState
from bot.awareness import AwarenessState
from bot.ego.planners import EconomyPlan
from bot.ego.strategy import StrategyState

from .knowledge.styles import BIO, ArmyStyle
from .policies import composition, investment
from .policies.composition import CompositionPolicy
from .policies.investment import InvestmentConfig


def plan(
    attention: AttentionState,
    strategy: StrategyState,
    army: ArmyStyle = BIO,
    enemy: Iterable[tuple[UnitTypeId, float]] = (),
    *,
    composition_policy: CompositionPolicy | None = None,
    investment_config: InvestmentConfig | None = None,
    awareness: AwarenessState | None = None,
) -> EconomyPlan:
    """`enemy` is the enemy army believed in, as power by unit type."""

    spend = investment.plan(attention, strategy, investment_config)
    enemy = tuple(enemy)
    policy = composition_policy or CompositionPolicy(army)
    if awareness is not None:
        enemy = awareness.seen_enemy_types
        contacts = awareness.contacts
        incidents = awareness.incidents
    else:
        contacts = ()
        incidents = ()
    composition_plan = policy.plan(
        attention, strategy, enemy, contacts=contacts, incidents=incidents
    )
    mix = composition_plan.units
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
            ("enemy_seen_power", sum(power for _, power in enemy)),
        ),
        upgrades=army.upgrades if invests else (),
        orbitals=spend.active,
        mules=spend.active,
        interrupt_opening=spend.interrupt_opening,
        max_production=spend.max_production,
        # An add-on stops its structure for half a minute: while stabilizing,
        # every resource goes to the army instead, as with the upgrades.
        addons=invests,
        addons_on=army.addons_on,
        reactor_share=composition.reactor_share(mix, army.addons_on),
        army=army.name,
        composition_plan=composition_plan,
    )

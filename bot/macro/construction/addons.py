from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId

from bot.engine.economy.models import EconomicActionKind, EconomicProposal
from bot.world.attention import EconomyFacts
from bot.world.awareness import MacroPosture

from ..proposal_helpers import build_proposal
from ..strategy.config import MacroPlannerConfig

# python-sc2 has no add-on -> parent table, and macro may not import Ares'
# (`ADD_ONS`) or the economy adapter's, so the six game facts are restated.
_PARENT_BY_ADDON: dict[UnitTypeId, UnitTypeId] = {
    UnitTypeId.BARRACKSREACTOR: UnitTypeId.BARRACKS,
    UnitTypeId.BARRACKSTECHLAB: UnitTypeId.BARRACKS,
    UnitTypeId.FACTORYREACTOR: UnitTypeId.FACTORY,
    UnitTypeId.FACTORYTECHLAB: UnitTypeId.FACTORY,
    UnitTypeId.STARPORTREACTOR: UnitTypeId.STARPORT,
    UnitTypeId.STARPORTTECHLAB: UnitTypeId.STARPORT,
}


def propose_addons(
    config: MacroPlannerConfig,
    planner_id: str,
    economy: EconomyFacts,
    posture: MacroPosture,
    now: float,
) -> tuple[EconomicProposal, ...]:
    """Ask for every add-on below its target that has somewhere to go.

    An add-on with no free parent is not argued for: the controller would
    reserve its cost against a purchase with nowhere to land -- a Tech Lab
    for a Factory the third base has not brought yet -- until dispatch
    times out, and then do it all over again.
    """

    proposals: list[EconomicProposal] = []
    for addon, desired, cost in config.goals.addons:
        current = economy.structure_count(addon).total
        if desired <= 0 or current >= desired:
            continue
        if _free_parents(economy, _PARENT_BY_ADDON[addon]) <= 0:
            continue
        proposals.append(
            build_proposal(
                planner_id=planner_id,
                kind=EconomicActionKind.BUILD_ADDON,
                category="addon",
                target=addon.name,
                current_count=current,
                desired_count=desired,
                priority=config.priority_for("addon", posture),
                reason="addon_count_below_strategy_target",
                cost=cost,
                now=now,
            )
        )
    return tuple(proposals)


def _free_parents(economy: EconomyFacts, parent: UnitTypeId) -> int:
    """Finished ``parent`` structures not holding or building an add-on.

    Counted from type totals, which works because an add-on takes the type
    of whatever it is attached to: a Factory that landed on the Barracks'
    Reactor holds a ``FACTORYREACTOR``.
    """

    held = sum(
        economy.structure_count(addon).total
        for addon, addon_parent in _PARENT_BY_ADDON.items()
        if addon_parent == parent
    )
    return economy.structure_count(parent).ready - held

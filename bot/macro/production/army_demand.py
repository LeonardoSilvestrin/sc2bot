from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.ids.unit_typeid import UnitTypeId

from bot.engine.economy.models import ResourceCost
from bot.world.attention import EconomyFacts

from ..strategy.goals import MacroGoalSet


@dataclass(frozen=True, slots=True)
class UnitDemand:
    """What one composition member is worth and how far behind it is."""

    unit_type: UnitTypeId
    ready: int
    pending: int
    desired: int
    cost: ResourceCost
    tech_ready: bool

    @property
    def total(self) -> int:
        return self.ready + self.pending

    @property
    def missing(self) -> int:
        return max(0, self.desired - self.total)

    @property
    def buildable_shortfall(self) -> int:
        """What is owed *and* possible to build right now.

        A Banshee we want but have no Starport for is still debt -- worth
        logging, worth teching towards -- but arguing for it would only
        reserve minerals against a purchase the game will not allow.
        """

        return self.missing if self.tech_ready else 0


@dataclass(frozen=True, slots=True)
class ArmyDemand:
    """How much army we should have, and which units are owed.

    The strategy's ``army_supply_target`` is the anchor: composition weights
    say *what* the debt should be paid in, never *whether* it exists. Meeting
    a member's minimum or its ratio share therefore cannot stop production
    while the army as a whole is still far below target -- the failure this
    layer exists to make impossible.
    """

    desired_supply: float
    ready_supply: float
    pending_supply: float
    units: tuple[UnitDemand, ...]

    @property
    def current_supply(self) -> float:
        return self.ready_supply + self.pending_supply

    @property
    def supply_debt(self) -> float:
        return max(0.0, self.desired_supply - self.current_supply)

    @property
    def producer_types_in_demand(self) -> frozenset[UnitTypeId]:
        """Structure types where *another one* would pay off the debt.

        Resolved from python-sc2's own tables rather than a hand-written
        unit-to-structure map. A unit needing a Tech Lab is deliberately not
        counted: a bare new Factory cannot build a Siege Tank either, so the
        bottleneck there is the add-on, and adding buildings would only park
        minerals in structures with nothing to make.
        """

        return self._producer_types(requires_techlab=False)

    @property
    def producer_types_needing_add_on(self) -> frozenset[UnitTypeId]:
        """Structure types whose owed units need an add-on to be built.

        Not a reason to build another structure -- a reason to say so, since
        "the Factory is idle and nothing wants a Factory" and "the Factory is
        idle because the Tank needs a Tech Lab" are very different problems.
        """

        return self._producer_types(requires_techlab=True)

    def _producer_types(self, *, requires_techlab: bool) -> frozenset[UnitTypeId]:
        return frozenset(
            structure_type
            for unit in self.units
            if unit.buildable_shortfall > 0
            for structure_type in UNIT_TRAINED_FROM.get(unit.unit_type, ())
            if bool(
                TRAIN_INFO.get(structure_type, {})
                .get(unit.unit_type, {})
                .get("requires_techlab", False)
            )
            is requires_techlab
        )


def army_demand(
    goals: MacroGoalSet,
    economy: EconomyFacts,
    *,
    supply_bonus: float = 0.0,
) -> ArmyDemand:
    """Scale the composition until it would reach the desired army supply.

    ``supply_bonus`` widens the target when the bank is overflowing: unspent
    resources are a reason to want a bigger army, not a reason to want more
    buildings (see ``construction.capacity``).
    """

    counts = {
        goal.unit_type: economy.unit_count(goal.unit_type) for goal in goals.army
    }
    desired_supply = goals.army_supply_target + supply_bonus
    supply_per_cycle = sum(goal.weight * goal.cost.supply for goal in goals.army)
    cycles = desired_supply / supply_per_cycle if supply_per_cycle > 0.0 else 0.0
    return ArmyDemand(
        desired_supply=desired_supply,
        ready_supply=sum(
            counts[goal.unit_type].ready * goal.cost.supply
            for goal in goals.army
        ),
        pending_supply=sum(
            counts[goal.unit_type].pending * goal.cost.supply
            for goal in goals.army
        ),
        units=tuple(
            UnitDemand(
                unit_type=goal.unit_type,
                ready=counts[goal.unit_type].ready,
                pending=counts[goal.unit_type].pending,
                desired=max(goal.minimum, ceil(goal.weight * cycles)),
                cost=goal.cost,
                tech_ready=economy.tech_ready_for(goal.unit_type),
            )
            for goal in goals.army
        ),
    )

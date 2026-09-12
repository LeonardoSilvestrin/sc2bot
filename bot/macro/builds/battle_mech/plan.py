"""Everything BattleMech intends to own after its scripted opening.

The opening itself is the ``BattleMech`` entry in ``terran_builds.yml``;
Ares requires that adapter file at repository root.  This module is the
strategy source for composition, production milestones and add-ons.
"""

from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId

from bot.engine.economy.models import ResourceCost

from ...composition import MECH
from ...strategy.goals import ArmyUnitGoal, MacroGoalSet, ProductionGoal


def battle_mech() -> MacroGoalSet:
    """Reaper-expand into a mobile Mech army with a Tank backbone.

    The opening leaves one Reactor Factory producing Hellions and one Tech Lab
    Starport producing the first cloaked Banshee.  Starting the third base
    unlocks two Tech Lab Factories and a second Starport.  Overflow may grow
    beyond three Factories only after the third is ready; it must never spend
    the third's bank on premature production capacity.
    """

    return MacroGoalSet(
        name="battle_mech",
        opening_name="BattleMech",
        max_workers=70,
        max_townhalls=4,
        workers_per_townhall=22,
        refineries_per_townhall=2,
        max_refineries=8,
        army_supply_target=110.0,
        army=(
            ArmyUnitGoal(
                UnitTypeId.HELLION,
                weight=3,
                minimum=4,
                cost=ResourceCost(minerals=100, supply=2.0),
            ),
            ArmyUnitGoal(
                UnitTypeId.CYCLONE,
                weight=2,
                minimum=1,
                cost=ResourceCost(minerals=125, vespene=50, supply=3.0),
            ),
            ArmyUnitGoal(
                UnitTypeId.SIEGETANK,
                weight=3,
                minimum=2,
                cost=ResourceCost(minerals=150, vespene=125, supply=3.0),
            ),
            ArmyUnitGoal(
                UnitTypeId.BANSHEE,
                weight=1,
                minimum=1,
                cost=ResourceCost(minerals=150, vespene=100, supply=3.0),
            ),
        ),
        production=(
            ProductionGoal(
                UnitTypeId.BARRACKS,
                minimum=1,
                maximum=1,
                cost=ResourceCost(minerals=150),
            ),
            ProductionGoal(
                UnitTypeId.FACTORY,
                minimum=1,
                maximum=5,
                cost=ResourceCost(minerals=150, vespene=100),
                vespene_rate_for_first_extra=900.0,
                vespene_rate_per_extra=450.0,
                # A pending third immediately starts the two planned
                # Factories; bank/income-based flood waits for it to finish.
                townhall_minimums=((3, 3),),
                dynamic_growth_minimum_ready_townhalls=3,
            ),
            ProductionGoal(
                UnitTypeId.STARPORT,
                minimum=1,
                maximum=2,
                cost=ResourceCost(minerals=150, vespene=100),
                townhall_minimums=((3, 2),),
                dynamic_growth_minimum_ready_townhalls=3,
            ),
        ),
        doctrine=MECH,
        addons=(
            # One for each Factory the third adds; the first keeps the Reactor.
            (
                UnitTypeId.FACTORYTECHLAB,
                2,
                ResourceCost(minerals=50, vespene=25),
            ),
            (
                UnitTypeId.STARPORTTECHLAB,
                2,
                ResourceCost(minerals=50, vespene=25),
            ),
        ),
    )

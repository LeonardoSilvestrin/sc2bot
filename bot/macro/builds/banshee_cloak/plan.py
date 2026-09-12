"""Composition, infrastructure and upgrades for the Banshee Cloak build."""

from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.engine.economy.models import ResourceCost

from ...composition import BIO
from ...strategy.goals import (
    ArmyUnitGoal,
    MacroGoalSet,
    ProductionGoal,
    UpgradeGoal,
)


def banshee_cloak() -> MacroGoalSet:
    """Keep two Tech Lab Starports active behind a small Bio/Tank floor."""

    return MacroGoalSet(
        name="banshee_cloak",
        opening_name="BansheeCloak",
        max_workers=70,
        max_townhalls=4,
        workers_per_townhall=22,
        refineries_per_townhall=2,
        max_refineries=8,
        army_supply_target=100.0,
        army=(
            ArmyUnitGoal(
                UnitTypeId.BANSHEE,
                weight=3,
                minimum=3,
                cost=ResourceCost(minerals=150, vespene=100, supply=3.0),
            ),
            ArmyUnitGoal(
                UnitTypeId.MARINE,
                weight=6,
                minimum=8,
                cost=ResourceCost(minerals=50, supply=1.0),
            ),
            ArmyUnitGoal(
                UnitTypeId.MARAUDER,
                weight=2,
                minimum=2,
                cost=ResourceCost(minerals=100, vespene=25, supply=2.0),
            ),
            ArmyUnitGoal(
                UnitTypeId.SIEGETANK,
                weight=2,
                minimum=2,
                cost=ResourceCost(minerals=150, vespene=125, supply=3.0),
            ),
        ),
        production=(
            ProductionGoal(
                UnitTypeId.BARRACKS,
                minimum=2,
                maximum=5,
                cost=ResourceCost(minerals=150),
                mineral_rate_for_first_extra=1_000.0,
                mineral_rate_per_extra=500.0,
            ),
            ProductionGoal(
                UnitTypeId.STARPORT,
                minimum=2,
                maximum=3,
                cost=ResourceCost(minerals=150, vespene=100),
                vespene_rate_for_first_extra=500.0,
                vespene_rate_per_extra=400.0,
            ),
            ProductionGoal(
                UnitTypeId.FACTORY,
                minimum=1,
                maximum=2,
                cost=ResourceCost(minerals=150, vespene=100),
            ),
        ),
        doctrine=BIO,
        addons=(
            (
                UnitTypeId.STARPORTTECHLAB,
                2,
                ResourceCost(minerals=50, vespene=25),
            ),
            (
                UnitTypeId.BARRACKSTECHLAB,
                1,
                ResourceCost(minerals=50, vespene=25),
            ),
            (
                UnitTypeId.FACTORYTECHLAB,
                1,
                ResourceCost(minerals=50, vespene=25),
            ),
        ),
        upgrades=(
            UpgradeGoal(
                UpgradeId.STIMPACK,
                ResourceCost(minerals=100, vespene=100),
            ),
            UpgradeGoal(
                UpgradeId.BANSHEESPEED,
                ResourceCost(minerals=150, vespene=150),
            ),
        ),
    )

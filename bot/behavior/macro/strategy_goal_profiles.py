from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.engine.economy.models import ResourceCost

from .macro_goals import (
    ArmyUnitGoal,
    MacroGoalSet,
    ProductionGoal,
    UpgradeGoal,
)


def bio_three_one_one() -> MacroGoalSet:
    """The initial dynamic macro profile after the Bio 3-1-1 opening.

    The returned frozen value is safe to replace with ``dataclasses.replace``
    in matchup-specific configuration or tests.
    """

    return MacroGoalSet(
        name="bio_three_one_one",
        opening_name="BioThreeOneOne",
        max_workers=70,
        max_townhalls=4,
        workers_per_townhall=22,
        refineries_per_townhall=2,
        max_refineries=8,
        army_supply_target=115.0,
        composition_lookahead=8,
        army=(
            ArmyUnitGoal(
                UnitTypeId.MARINE,
                weight=8,
                minimum=12,
                cost=ResourceCost(minerals=50, supply=1.0),
            ),
            ArmyUnitGoal(
                UnitTypeId.MARAUDER,
                weight=3,
                minimum=4,
                cost=ResourceCost(minerals=100, vespene=25, supply=2.0),
            ),
            ArmyUnitGoal(
                UnitTypeId.MEDIVAC,
                weight=2,
                minimum=2,
                cost=ResourceCost(minerals=100, vespene=100, supply=2.0),
                priority_offset=2,
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
                minimum=3,
                maximum=8,
                cost=ResourceCost(minerals=150),
                mineral_rate_for_first_extra=1_200.0,
                mineral_rate_per_extra=500.0,
            ),
            ProductionGoal(
                UnitTypeId.FACTORY,
                minimum=1,
                maximum=3,
                cost=ResourceCost(minerals=150, vespene=100),
                vespene_rate_for_first_extra=650.0,
                vespene_rate_per_extra=450.0,
            ),
            ProductionGoal(
                UnitTypeId.STARPORT,
                minimum=1,
                maximum=3,
                cost=ResourceCost(minerals=150, vespene=100),
                vespene_rate_for_first_extra=800.0,
                vespene_rate_per_extra=500.0,
            ),
        ),
        addons=(
            (
                UnitTypeId.BARRACKSTECHLAB,
                2,
                ResourceCost(minerals=50, vespene=25),
            ),
            (
                UnitTypeId.FACTORYTECHLAB,
                1,
                ResourceCost(minerals=50, vespene=25),
            ),
            (
                UnitTypeId.STARPORTREACTOR,
                1,
                ResourceCost(minerals=50, vespene=50),
            ),
        ),
        upgrades=(
            UpgradeGoal(
                UpgradeId.STIMPACK,
                ResourceCost(minerals=100, vespene=100),
            ),
            UpgradeGoal(
                UpgradeId.SHIELDWALL,
                ResourceCost(minerals=100, vespene=100),
            ),
            UpgradeGoal(
                UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,
                ResourceCost(minerals=100, vespene=100),
            ),
        ),
    )


def banshee_cloak() -> MacroGoalSet:
    """Post-opening convergence for the ``BansheeCloak`` opener.

    Cloak itself is already researched during the opening (see
    ``terran_builds.yml``); this only keeps Banshees flowing out of the
    Starport afterward and backs them with a Marine/Marauder floor so the
    army is not entirely grounded-air. Lower ``army_supply_target`` and
    ``composition_lookahead`` than ``bio_three_one_one`` -- Banshees are
    expensive per supply and this profile leans on harass pressure rather
    than a large standing army.
    """

    return MacroGoalSet(
        name="banshee_cloak",
        opening_name="BansheeCloak",
        max_workers=70,
        max_townhalls=4,
        workers_per_townhall=22,
        refineries_per_townhall=2,
        max_refineries=8,
        army_supply_target=100.0,
        composition_lookahead=6,
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
                minimum=1,
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
        addons=(
            (
                UnitTypeId.STARPORTREACTOR,
                1,
                ResourceCost(minerals=50, vespene=50),
            ),
            (
                UnitTypeId.BARRACKSTECHLAB,
                1,
                ResourceCost(minerals=50, vespene=25),
            ),
        ),
        upgrades=(
            UpgradeGoal(
                UpgradeId.STIMPACK,
                ResourceCost(minerals=100, vespene=100),
            ),
        ),
    )

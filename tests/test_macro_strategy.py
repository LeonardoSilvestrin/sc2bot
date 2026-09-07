from __future__ import annotations

from dataclasses import replace

import pytest
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.behavior.macro import MacroGoalSet, ProductionGoal, bio_three_one_one


def test_bio_three_one_one_declares_full_post_opening_convergence():
    goals = bio_three_one_one()

    assert goals.opening_name == "BioThreeOneOne"
    assert {goal.unit_type for goal in goals.army} == {
        UnitTypeId.MARINE,
        UnitTypeId.MARAUDER,
        UnitTypeId.MEDIVAC,
        UnitTypeId.SIEGETANK,
    }
    assert {goal.structure_type: goal.minimum for goal in goals.production} == {
        UnitTypeId.BARRACKS: 3,
        UnitTypeId.FACTORY: 1,
        UnitTypeId.STARPORT: 1,
    }
    assert {goal.upgrade_id for goal in goals.upgrades} == {
        UpgradeId.STIMPACK,
        UpgradeId.SHIELDWALL,
        UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,
    }


def test_profile_is_configurable_as_an_immutable_value():
    original = bio_three_one_one()
    greedy_four_base = replace(original, max_workers=76, max_townhalls=5)

    assert original.max_workers == 70
    assert original.max_townhalls == 4
    assert greedy_four_base.max_workers == 76
    assert greedy_four_base.max_townhalls == 5


def test_production_goal_scales_and_caps_income_target():
    goal = ProductionGoal(
        UnitTypeId.BARRACKS,
        minimum=3,
        maximum=5,
        cost=bio_three_one_one().production[0].cost,
        mineral_rate_for_first_extra=1_000.0,
        mineral_rate_per_extra=500.0,
    )

    assert goal.target_for_income(minerals=999.0, vespene=0.0) == 3
    assert goal.target_for_income(minerals=1_000.0, vespene=0.0) == 4
    assert goal.target_for_income(minerals=1_500.0, vespene=0.0) == 5
    assert goal.target_for_income(minerals=9_000.0, vespene=0.0) == 5


def test_goal_set_rejects_duplicate_army_targets():
    original = bio_three_one_one()

    with pytest.raises(ValueError, match="army unit goals must be unique"):
        MacroGoalSet(
            name=original.name,
            opening_name=original.opening_name,
            max_workers=original.max_workers,
            max_townhalls=original.max_townhalls,
            workers_per_townhall=original.workers_per_townhall,
            refineries_per_townhall=original.refineries_per_townhall,
            max_refineries=original.max_refineries,
            army_supply_target=original.army_supply_target,
            composition_lookahead=original.composition_lookahead,
            army=(original.army[0], original.army[0]),
            production=original.production,
        )

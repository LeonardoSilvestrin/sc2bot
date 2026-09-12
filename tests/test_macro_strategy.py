from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from ares.consts import ADD_ONS
from ares.dicts.unit_tech_requirement import UNIT_TECH_REQUIREMENT
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.engine.economy.models import ResourceCost
from bot.macro import (
    MECH,
    MacroGoalSet,
    ProductionGoal,
    banshee_cloak,
    battle_mech,
    bio_three_one_one,
)


def test_banshee_cloak_declares_a_banshee_led_composition():
    goals = banshee_cloak()

    assert goals.opening_name == "BansheeCloak"
    assert UnitTypeId.BANSHEE in {goal.unit_type for goal in goals.army}
    assert {goal.structure_type: goal.minimum for goal in goals.production} == {
        UnitTypeId.BARRACKS: 2,
        UnitTypeId.STARPORT: 2,
        UnitTypeId.FACTORY: 1,
    }
    assert {addon: target for addon, target, _cost in goals.addons}[
        UnitTypeId.STARPORTTECHLAB
    ] == 2
    assert UnitTypeId.STARPORTREACTOR not in {
        addon for addon, _target, _cost in goals.addons
    }
    assert UpgradeId.BANSHEESPEED in {goal.upgrade_id for goal in goals.upgrades}


def test_battle_mech_buys_mech_and_grows_production_with_the_third_base():
    goals = battle_mech()
    production = {goal.structure_type: goal for goal in goals.production}

    assert goals.opening_name == "BattleMech"
    assert goals.doctrine is MECH
    assert {goal.unit_type for goal in goals.army} == {
        UnitTypeId.HELLION,
        UnitTypeId.CYCLONE,
        UnitTypeId.SIEGETANK,
        UnitTypeId.BANSHEE,
    }
    assert [production[UnitTypeId.FACTORY].minimum_for(n) for n in (1, 2, 3, 4)] == [
        1,
        1,
        3,
        3,
    ]
    assert [production[UnitTypeId.STARPORT].minimum_for(n) for n in (2, 3)] == [1, 2]
    assert production[UnitTypeId.BARRACKS].maximum == 1


def test_townhall_minimums_stay_within_the_goal_bounds():
    with pytest.raises(ValueError, match="townhall_minimums"):
        ProductionGoal(
            UnitTypeId.STARPORT,
            minimum=1,
            maximum=2,
            cost=ResourceCost(minerals=150, vespene=100),
            townhall_minimums=((3, 3),),
        )


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


def opening_structures(opening_name: str) -> set[UnitTypeId]:
    """Structure and add-on types the opening itself builds."""

    builds = yaml.safe_load(Path("terran_builds.yml").read_text())["Builds"]
    steps = builds[opening_name]["OpeningBuildOrder"]
    names = {
        token.upper()
        for step in steps
        for token in str(step).replace("@", " ").replace("*", " ").split()
    }
    return {unit_type for unit_type in UnitTypeId if unit_type.name in names}


@pytest.mark.parametrize("profile", [bio_three_one_one, banshee_cloak, battle_mech])
def test_every_composition_member_has_the_add_ons_it_needs(profile):
    """A unit whose tech never arrives is worse than a unit not wanted.

    It reads as permanent army debt that no amount of banked minerals can
    pay off, and the structure that would have built it stands idle for the
    rest of the game. The tech can come from the opening or from the
    profile's own add-on goals; checked against Ares' tech table so a
    composition change cannot quietly reintroduce the gap.
    """

    goals = profile()
    planned = {addon for addon, target, _cost in goals.addons if target > 0}
    planned.update(goal.structure_type for goal in goals.production)
    planned.update(opening_structures(goals.opening_name))

    for goal in goals.army:
        required = UNIT_TECH_REQUIREMENT.get(goal.unit_type, set())
        missing = {
            requirement
            for requirement in required
            if requirement in ADD_ONS and requirement not in planned
        }
        assert not missing, (
            f"{goals.name} wants {goal.unit_type.name} but never builds "
            f"{ {item.name for item in missing} }"
        )


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
            army=(original.army[0], original.army[0]),
            production=original.production,
            doctrine=original.doctrine,
        )

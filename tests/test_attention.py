"""The power model: what one unit is worth in a fight, in Marines."""

from __future__ import annotations

import math

import pytest
from sc2.ids.unit_typeid import UnitTypeId

from bot.attention import SPLASH_TARGETS, unit_power, unit_view

from .fakes import FakeUnit

# What python-sc2 reports for a Siege Tank in siege: 40 damage every 2.14 s
# over 175 hit points.
TANK_DPS = 40.0 / 2.14
TANK_HIT_POINTS = 175.0


def supply(_type_id) -> float:
    return 3.0


def test_a_marine_is_one_marine() -> None:
    assert unit_power(9.8, 45.0) == pytest.approx(1.0)
    assert SPLASH_TARGETS.get(UnitTypeId.MARINE, 1.0) == 1.0


def test_a_shot_that_covers_three_targets_is_worth_three_shots() -> None:
    """Splash multiplies the damage a unit puts out, so it multiplies the
    damage inside the square root: three targets are sqrt(3) of the power."""

    single = unit_power(9.8, 45.0)

    assert unit_power(9.8, 45.0, 3.0) == pytest.approx(single * math.sqrt(3.0))
    # A shot always covers the target it is aimed at, and nothing makes a unit
    # worth less than its own damage.
    assert unit_power(9.8, 45.0, 0.0) == pytest.approx(single)
    assert unit_power(9.8, 45.0, -2.0) == pytest.approx(single)


def test_the_sieged_tank_is_priced_with_its_splash_and_the_tank_moving_is_not() -> None:
    """bench/base3/007: the bio ball walked into a line of sieged tanks priced
    at 2.7 Marines each. The same tank out of siege has no splash at all."""

    sieged = unit_view(
        FakeUnit(900, UnitTypeId.SIEGETANKSIEGED, 50.0, 50.0,
                 dps=TANK_DPS, hit_points=TANK_HIT_POINTS),
        supply,
    )
    moving = unit_view(
        FakeUnit(901, UnitTypeId.SIEGETANK, 50.0, 50.0,
                 dps=TANK_DPS, hit_points=TANK_HIT_POINTS),
        supply,
    )

    assert moving.power == pytest.approx(2.72, abs=0.01)
    assert sieged.power == pytest.approx(moving.power * math.sqrt(2.5), abs=0.01)
    assert sieged.power == pytest.approx(4.31, abs=0.01)


def test_splash_prices_the_damage_dealt_and_not_the_damage_taken() -> None:
    """A tank at half its hit points is worth sqrt(0.5) of a whole one, with
    splash as without it: the shot still covers the same ground."""

    whole = unit_view(
        FakeUnit(900, UnitTypeId.SIEGETANKSIEGED, 50.0, 50.0,
                 dps=TANK_DPS, hit_points=TANK_HIT_POINTS),
        supply,
    )
    hurt = unit_view(
        FakeUnit(901, UnitTypeId.SIEGETANKSIEGED, 50.0, 50.0,
                 dps=TANK_DPS, hit_points=TANK_HIT_POINTS, health=TANK_HIT_POINTS / 2.0),
        supply,
    )

    assert hurt.power == pytest.approx(whole.power * math.sqrt(0.5))


def test_a_unit_with_no_splash_keeps_its_price() -> None:
    zergling = unit_view(
        FakeUnit(700, UnitTypeId.ZERGLING, 50.0, 50.0, dps=10.0, hit_points=35.0),
        supply,
    )

    assert zergling.power == pytest.approx(unit_power(10.0, 35.0))

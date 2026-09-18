from __future__ import annotations

import pytest
from sc2.ids.unit_typeid import UnitTypeId

from bot.ego.planners.economy import composition, styles


def shares(style, enemy) -> dict[UnitTypeId, float]:
    return {unit_type: share for unit_type, share, _ in composition.mix(style, enemy)}


def prior(style) -> dict[UnitTypeId, float]:
    return {unit_type: share for unit_type, share, _ in style.composition}


@pytest.mark.parametrize("style", list(styles.STYLES.values()), ids=list(styles.STYLES))
def test_with_nothing_seen_the_mix_is_the_style(style) -> None:
    assert composition.mix(style, ()) == style.composition


def test_mutalisks_turn_mech_away_from_what_cannot_shoot_up() -> None:
    mix = shares(styles.MECH, ((UnitTypeId.MUTALISK, 40.0),))
    base = prior(styles.MECH)

    assert sum(mix.values()) == pytest.approx(1.0)
    assert mix[UnitTypeId.CYCLONE] > base[UnitTypeId.CYCLONE]
    assert mix[UnitTypeId.HELLION] < base[UnitTypeId.HELLION]
    assert mix[UnitTypeId.SIEGETANK] < base[UnitTypeId.SIEGETANK]


def test_lings_turn_mech_toward_hellions_and_roaches_toward_tanks() -> None:
    base = prior(styles.MECH)
    lings = shares(styles.MECH, ((UnitTypeId.ZERGLING, 40.0),))
    roaches = shares(styles.MECH, ((UnitTypeId.ROACH, 40.0),))

    assert lings[UnitTypeId.HELLION] > base[UnitTypeId.HELLION]
    assert roaches[UnitTypeId.SIEGETANK] > base[UnitTypeId.SIEGETANK]
    assert roaches[UnitTypeId.HELLION] < base[UnitTypeId.HELLION]


def test_the_mix_slides_with_how_much_was_seen_without_a_threshold() -> None:
    hellion = [
        shares(styles.MECH, ((UnitTypeId.ROACH, power),))[UnitTypeId.HELLION]
        for power in (0.0, 1.0, 5.0, 20.0, 80.0, 320.0)
    ]

    assert hellion == sorted(hellion, reverse=True)
    assert len(set(hellion)) == len(hellion)


def test_support_keeps_its_prior_value_and_the_priorities_stay() -> None:
    enemy = ((UnitTypeId.ROACH, 30.0), (UnitTypeId.MUTALISK, 10.0))

    assert composition.value(UnitTypeId.MEDIVAC, enemy, 40.0) == 1.0
    assert [priority for *_, priority in composition.mix(styles.BIO, enemy)] == [
        priority for *_, priority in styles.BIO.composition
    ]


@pytest.mark.parametrize("style", list(styles.STYLES.values()), ids=list(styles.STYLES))
def test_every_unit_of_every_style_knows_what_it_can_shoot(style) -> None:
    for unit_type, _, _ in style.composition:
        assert unit_type in composition.REACH

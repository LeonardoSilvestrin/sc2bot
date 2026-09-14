from __future__ import annotations

import math

import numpy as np
import pytest
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.awareness import AwarenessModel

from .fakes import MAIN, attention, seen_everywhere, unit


def zergling(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.ZERGLING, x, y, power=0.9, supply=0.5, attack_air=False)


def mutalisk(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.MUTALISK, x, y, power=1.2, supply=2.0, flying=True)


def test_a_contact_out_of_sight_is_remembered_fading_and_drifting() -> None:
    model = AwarenessModel()
    model.infer(attention(time=0.0, enemy_units=(zergling(1, 40, 40),)))

    after_5 = model.infer(attention(time=5.0)).contacts[0]
    after_10 = model.infer(attention(time=10.0)).contacts[0]

    assert not after_5.visible
    assert after_5.position == Point2((40.0, 40.0))
    assert after_5.confidence == pytest.approx(math.exp(-5.0 / 20.0))
    assert after_10.confidence < after_5.confidence
    assert after_5.uncertainty == pytest.approx(14.0)
    assert after_10.uncertainty == pytest.approx(16.0)


def test_a_contact_is_forgotten_when_confirmed_dead() -> None:
    model = AwarenessModel()
    model.infer(attention(time=0.0, enemy_units=(zergling(1, 40, 40),)))

    assert model.infer(attention(time=1.0, dead_tags=(1,))).contacts == ()


def test_an_empty_last_position_forgets_the_contact_only_after_the_grace() -> None:
    model = AwarenessModel()
    model.infer(attention(time=0.0, enemy_units=(zergling(1, 40, 40),)))

    assert model.infer(attention(time=1.0, visibility=seen_everywhere())).contacts
    assert model.infer(attention(time=2.5, visibility=seen_everywhere())).contacts == ()


def test_a_contact_fades_out_of_memory() -> None:
    model = AwarenessModel()
    model.infer(attention(time=0.0, enemy_units=(zergling(1, 40, 40),)))

    assert model.infer(attention(time=50.0)).contacts
    assert model.infer(attention(time=70.0)).contacts == ()


def test_a_structure_stays_where_it_was_seen() -> None:
    model = AwarenessModel()
    hatchery = unit(5, UnitTypeId.HATCHERY, 50, 50, power=0.0, structure=True)
    model.infer(attention(time=0.0, enemy_structures=(hatchery,)))

    contact = model.infer(attention(time=60.0)).contacts[0]

    assert contact.uncertainty == 0.0
    assert contact.confidence > 0.7


def test_base_pressure_grows_with_proximity_and_numbers() -> None:
    def base_threat(*attackers):
        return AwarenessModel().infer(attention(enemy_units=attackers)).bases[0]

    calm = base_threat()
    far = base_threat(zergling(1, 30.0, 10.5))
    near = base_threat(zergling(1, 16.0, 10.5))
    many = base_threat(*(zergling(tag, 16.0, 10.5) for tag in range(1, 4)))

    assert calm.pressure == 0.0 and calm.threat == 0.0 and calm.center is None
    assert 0.0 < far.threat < near.threat < many.threat < 1.0
    assert many.center == Point2((16.0, 10.5))


def test_an_attacker_beyond_reach_puts_no_pressure() -> None:
    state = AwarenessModel().infer(attention(enemy_units=(zergling(1, 50, 50),)))

    assert state.bases[0].pressure == 0.0
    assert state.danger == 0.0
    assert state.most_threatened is None


def test_air_share_is_the_flying_part_of_the_pressure() -> None:
    mixed = (
        AwarenessModel()
        .infer(attention(enemy_units=(zergling(1, 15, 10.5), mutalisk(2, 15, 10.5))))
        .bases[0]
    )
    air = AwarenessModel().infer(attention(enemy_units=(mutalisk(2, 15, 10.5),))).bases[0]

    assert 0.0 < mixed.air_share < 1.0
    assert air.air_share == pytest.approx(1.0)


def test_cover_counts_our_army_at_the_base() -> None:
    state = AwarenessModel().infer(
        attention(
            own_units=(
                unit(10, x=12, y=10.5),
                unit(11, UnitTypeId.SCV, 11, 10, power=0.6, worker=True),
            ),
            enemy_units=(zergling(1, 15, 10.5),),
        )
    )
    base = state.bases[0]

    assert base.base_id == MAIN.base_id
    assert base.cover == pytest.approx(math.exp(-0.5 * 1.5**2 / 14.0**2))
    assert 0.0 < base.balance < 1.0
    assert state.own_power == pytest.approx(1.0)


def test_uncertainty_widens_possible_threat_but_not_credible_presence() -> None:
    model = AwarenessModel()
    seen = model.infer(attention(time=0.0, enemy_units=(zergling(1, 40, 40),)))
    index = seen.influence.nearest(Point2((50.0, 40.0)))
    remembered = model.infer(attention(time=5.0))

    assert remembered.influence.threat[index] > seen.influence.threat[index]
    assert remembered.influence.enemy[index] < seen.influence.enemy[index]


def test_field_readings_stay_in_the_unit_interval() -> None:
    crowd = tuple(zergling(tag, 30 + tag % 5, 30 + tag % 7) for tag in range(1, 60))
    army = tuple(unit(100 + tag, x=20, y=20, power=3.0) for tag in range(30))
    field = AwarenessModel().infer(attention(own_units=army, enemy_units=crowd)).influence

    for reading in (field.threat, field.support, field.enemy):
        assert np.all(reading >= 0.0) and np.all(reading < 1.0)
    assert np.all(np.abs(field.control) < 1.0)
    assert field.summary()["samples"] == len(field.positions)


def test_the_same_frames_give_the_same_beliefs() -> None:
    frames = (
        attention(time=0.0, enemy_units=(zergling(1, 15, 10.5), mutalisk(2, 40, 40))),
        attention(time=3.0, enemy_units=(zergling(1, 16, 11),)),
        attention(time=6.0, dead_tags=(1,)),
    )
    first, second = AwarenessModel(), AwarenessModel()
    for frame in frames:
        a, b = first.infer(frame), second.infer(frame)
        assert a == b
        assert np.array_equal(a.influence.threat, b.influence.threat)

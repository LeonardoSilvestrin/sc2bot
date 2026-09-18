from __future__ import annotations

import math

import numpy as np
import pytest
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.awareness import AwarenessConfig, AwarenessModel

from .fakes import MAIN, NATURAL, attention, seen_everywhere, unit


def zergling(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.ZERGLING, x, y, power=0.9, supply=0.5, attack_air=False)


def mutalisk(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.MUTALISK, x, y, power=1.2, supply=2.0, flying=True)


def roach(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.ROACH, x, y, power=1.5, supply=2.0, attack_air=False)


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


def test_a_base_remembers_its_threat_fading_and_a_stronger_attack_counts_at_once() -> None:
    model = AwarenessModel()
    tau = model.config.threat_memory
    x, y = MAIN.position
    first = model.infer(
        attention(time=0.0, enemy_units=tuple(unit(tag, x=x, y=y) for tag in range(1, 5)))
    )
    lull = model.infer(attention(time=5.0, dead_tags=range(1, 5)))
    later = model.infer(attention(time=10.0))
    stronger = model.infer(
        attention(time=11.0, enemy_units=tuple(unit(tag, x=x, y=y) for tag in range(11, 17)))
    )
    model.infer(attention(time=12.0, dead_tags=range(11, 17)))
    faded = stronger.bases[0].threat * math.exp(-(80.0 - 11.0) / tau)
    gone = model.infer(attention(time=80.0))

    peak = 1.0 - math.exp(-1.0)
    assert first.bases[0].threat == first.bases[0].recent_threat == pytest.approx(peak)
    assert lull.bases[0].threat == lull.danger_now == 0.0
    assert lull.danger == pytest.approx(peak * math.exp(-5.0 / tau))
    assert lull.most_threatened is not None and lull.most_threatened.base_id == MAIN.base_id
    assert later.danger == pytest.approx(peak * math.exp(-10.0 / tau))
    assert stronger.danger == stronger.bases[0].threat == pytest.approx(1.0 - math.exp(-1.5))
    assert faded < model.config.forget_below
    assert gone.danger == 0.0 and gone.most_threatened is None


def test_an_attacker_beyond_reach_puts_no_pressure() -> None:
    state = AwarenessModel().infer(attention(enemy_units=(zergling(1, 50, 50),)))

    assert state.bases[0].pressure == 0.0
    assert state.danger == 0.0
    assert state.most_threatened is None
    assert state.incidents == ()


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


def test_one_attacker_in_reach_of_two_bases_is_one_incident() -> None:
    state = AwarenessModel().infer(
        attention(bases=(MAIN, NATURAL), enemy_units=(zergling(7, 20, 12),))
    )

    (incident,) = state.incidents
    assert (incident.incident_id, incident.contacts) == ("incident:7", (7,))
    assert incident.affected_bases == (MAIN.base_id, NATURAL.base_id)
    assert incident.center == Point2((20.0, 12.0))
    assert incident.ground_power == pytest.approx(0.9)
    assert incident.air_power == 0.0
    assert incident.threat == pytest.approx(state.danger)
    for base in state.bases:
        assert dict(incident.pressure_by_base)[base.base_id] == pytest.approx(base.pressure)


def test_attackers_chained_close_together_are_one_incident_named_by_its_lowest_tag() -> None:
    state = AwarenessModel().infer(
        attention(
            bases=(MAIN, NATURAL),
            enemy_units=(
                zergling(5, 14, 10),
                zergling(3, 24, 10),
                zergling(8, 34, 10),
                mutalisk(2, 10, 30),
            ),
        )
    )

    assert [(item.incident_id, item.contacts) for item in state.incidents] == [
        ("incident:2", (2,)),
        ("incident:3", (3, 5, 8)),
    ]
    air, ground = state.incidents
    assert (air.air_power, air.ground_power) == (pytest.approx(1.2), 0.0)
    assert ground.power == pytest.approx(2.7)
    # Every attacker in reach is in exactly one incident: they add up to each base.
    for base in state.bases:
        assert sum(
            dict(item.pressure_by_base).get(base.base_id, 0.0) for item in state.incidents
        ) == pytest.approx(base.pressure)


def test_an_incident_id_holds_splits_merges_and_is_remembered_by_rule() -> None:
    model = AwarenessModel()

    def incidents(time: float, *enemies):
        state = model.infer(attention(time=time, enemy_units=enemies))
        return [(item.incident_id, item.contacts) for item in state.incidents]

    assert incidents(0.0, zergling(3, 14, 10), zergling(5, 20, 10)) == [("incident:3", (3, 5))]
    assert incidents(1.0, zergling(3, 15, 11), zergling(5, 21, 11)) == [("incident:3", (3, 5))]
    assert incidents(2.0, zergling(3, 14, 10), zergling(5, 14, 32)) == [
        ("incident:3", (3,)),
        ("incident:5", (5,)),
    ]
    assert incidents(3.0, zergling(3, 14, 10), zergling(5, 16, 12)) == [("incident:3", (3, 5))]
    # Out of sight, the remembered contacts keep the incident, fading.
    assert incidents(4.0) == [("incident:3", (3, 5))]
    assert model.infer(attention(time=5.0)).incidents[0].confidence == pytest.approx(
        math.exp(-2.0 / 20.0)
    )


def test_an_incident_keeps_its_id_when_its_lowest_tag_leaves() -> None:
    # bench/7g 001, 520.4 s: the contact that named an incident of seven left
    # it, and the same attack took another id; the defense proposal was renamed
    # with it and the Engine moved its units as if to a new demand (100-165
    # defense-to-defense transfers a game in bench/7g).
    model = AwarenessModel()

    def incidents(time: float, *enemies, dead=()):
        state = model.infer(attention(time=time, enemy_units=enemies, dead_tags=dead))
        return [(item.incident_id, item.contacts) for item in state.incidents]

    assert incidents(0.0, zergling(3, 14, 10), zergling(5, 16, 10), zergling(8, 18, 10)) == [
        ("incident:3", (3, 5, 8))
    ]
    assert incidents(0.5, zergling(5, 16, 10), zergling(8, 18, 10), dead=(3,)) == [
        ("incident:3", (5, 8))
    ]
    # A newcomer with a lower tag joins it and does not rename it either.
    assert incidents(1.0, zergling(1, 15, 10), zergling(5, 16, 10), zergling(8, 18, 10)) == [
        ("incident:3", (1, 5, 8))
    ]


def test_a_split_leaves_the_id_with_most_of_the_incident_and_a_merge_with_the_largest() -> None:
    model = AwarenessModel()

    def incidents(time: float, *enemies):
        state = model.infer(attention(time=time, enemy_units=enemies))
        return [(item.incident_id, item.contacts) for item in state.incidents]

    group = (zergling(5, 16, 10), zergling(8, 18, 10))
    assert incidents(0.0, zergling(3, 14, 10), *group) == [("incident:3", (3, 5, 8))]
    # The lowest tag walks off alone: the two it left keep the id, and it
    # takes its own tag, suffixed because that id is taken.
    assert incidents(0.5, zergling(3, 14, 32), *group) == [
        ("incident:3-1", (3,)),
        ("incident:3", (5, 8)),
    ]
    # Merged again, the larger part's id wins.
    assert incidents(1.0, zergling(3, 14, 10), *group) == [("incident:3", (3, 5, 8))]

    # Two incidents of different sizes merge: the larger one's id wins,
    # although the other had the lower tag.
    model = AwarenessModel()
    far = (zergling(5, 14, 32), zergling(8, 16, 32), zergling(9, 18, 32))
    assert incidents(0.0, zergling(3, 14, 10), *far) == [
        ("incident:3", (3,)),
        ("incident:5", (5, 8, 9)),
    ]
    near = (zergling(5, 15, 12), zergling(8, 16, 12), zergling(9, 17, 12))
    assert incidents(0.5, zergling(3, 14, 10), *near) == [("incident:5", (3, 5, 8, 9))]


def test_enemy_workers_and_structures_are_no_army() -> None:
    # Trace 6455342, 95-180 s: a worker scout's look at a Zerg mineral line put
    # ~20 Drones into enemy_power, 9.3 Marines against no army of ours.
    drones = tuple(
        unit(tag, UnitTypeId.DRONE, 50 + tag % 4, 50, power=0.55, worker=True, attack_air=False)
        for tag in range(1, 17)
    )
    structures = (
        unit(30, UnitTypeId.HATCHERY, 53, 53, power=0.0, structure=True),
        unit(31, UnitTypeId.SPINECRAWLER, 48, 53, power=1.4, structure=True, attack_air=False),
    )
    state = AwarenessModel().infer(
        attention(
            time=100.0,
            enemy_units=(*drones, zergling(20, 45, 45)),
            enemy_structures=structures,
        )
    )

    assert len(state.contacts) == 19
    assert state.enemy_power == state.seen_enemy_power == pytest.approx(0.9)


def test_an_army_out_of_sight_is_believed_alive_until_it_is_seen_to_die() -> None:
    config = AwarenessConfig(army_growth=0.0)
    model = AwarenessModel(config)
    tau = config.army_memory
    seen = model.infer(
        attention(time=200.0, enemy_units=tuple(roach(tag, 40, 40) for tag in range(1, 6)))
    )
    # Out of sight, a fading contact still places part of it ...
    hidden = model.infer(attention(time=210.0))
    # ... and none does once its last position is back in sight without it.
    moved = model.infer(attention(time=213.0, visibility=seen_everywhere()))
    later = model.infer(attention(time=290.0))
    fewer = model.infer(attention(time=291.0, dead_tags=(1, 2, 3)))
    gone = model.infer(attention(time=200.0 + tau * math.log(1.0 / config.forget_below) + 1.0))

    assert seen.enemy_power == seen.estimated_enemy_power == pytest.approx(7.5)
    assert (seen.enemy_uncertainty, seen.enemy_coverage) == (0.0, 1.0)
    assert hidden.enemy_power == pytest.approx(7.5 * math.exp(-10.0 / config.unit_memory))
    assert hidden.seen_enemy_power == pytest.approx(7.5 * math.exp(-10.0 / tau))
    assert hidden.enemy_uncertainty == pytest.approx(
        hidden.seen_enemy_power - hidden.enemy_power
    )
    assert moved.contacts == () and moved.enemy_power == 0.0
    assert moved.seen_enemy_power == pytest.approx(7.5 * math.exp(-13.0 / tau))
    assert moved.enemy_uncertainty == moved.estimated_enemy_power == moved.seen_enemy_power
    assert moved.enemy_coverage == 0.0
    assert later.seen_enemy_power == pytest.approx(7.5 * math.exp(-90.0 / tau))
    assert fewer.seen_enemy_power == pytest.approx(3.0 * math.exp(-91.0 / tau))
    assert gone.seen_enemy_power == gone.estimated_enemy_power == 0.0
    for state in (seen, hidden, moved, later, fewer, gone):
        assert state.enemy_power <= state.seen_enemy_power


@pytest.mark.parametrize(
    "time, expected", [(60.0, 0.0), (320.0, 20.0), (600.0, 48.0), (2000.0, 100.0)]
)
def test_an_enemy_never_seen_is_expected_an_army_growing_to_a_cap(
    time: float, expected: float
) -> None:
    state = AwarenessModel().infer(attention(time=time))

    assert state.enemy_power == state.seen_enemy_power == 0.0
    assert state.estimated_enemy_power == pytest.approx(expected)
    assert state.enemy_uncertainty == pytest.approx(expected)
    assert state.enemy_coverage == (1.0 if expected == 0.0 else 0.0)


def test_a_fresh_sighting_of_more_than_the_expected_army_leaves_no_uncertainty() -> None:
    army = tuple(roach(tag, 50, 50) for tag in range(1, 41))
    state = AwarenessModel().infer(attention(time=600.0, enemy_units=army))

    assert state.expected_enemy_power == pytest.approx(48.0)
    assert state.enemy_power == state.estimated_enemy_power == pytest.approx(60.0)
    assert (state.enemy_uncertainty, state.enemy_coverage) == (0.0, 1.0)


@pytest.mark.parametrize(
    "change",
    [{"army_memory": 10.0}, {"army_growth": -0.1}, {"army_onset": -1.0}, {"army_cap": -1.0}],
)
def test_an_invalid_army_estimate_is_rejected(change: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        AwarenessConfig(**change)


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


def test_the_seen_army_is_told_by_type_heaviest_first_and_forgets_the_dead() -> None:
    model = AwarenessModel()
    tau = model.config.army_memory
    seen = model.infer(
        attention(
            time=200.0,
            enemy_units=(zergling(1, 40, 40), zergling(2, 41, 40), roach(3, 42, 40)),
        )
    )
    later = model.infer(attention(time=260.0, dead_tags=(3,)))

    assert seen.seen_enemy_types == (
        (UnitTypeId.ZERGLING, pytest.approx(1.8)),
        (UnitTypeId.ROACH, pytest.approx(1.5)),
    )
    assert sum(power for _, power in seen.seen_enemy_types) == pytest.approx(
        seen.seen_enemy_power
    )
    assert later.seen_enemy_types == (
        (UnitTypeId.ZERGLING, pytest.approx(1.8 * math.exp(-60.0 / tau))),
    )

from __future__ import annotations

from dataclasses import replace

import pytest
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId

from bot.awareness import AwarenessModel, EnemyArmyBelief
from bot.ego.planners.economy.knowledge import styles
from bot.ego.planners.economy.policies import composition
from bot.ego.strategy import StrategyModel

from .fakes import attention, unit

EVERYTHING = {
    UnitTypeId.MARINE,
    UnitTypeId.MARAUDER,
    UnitTypeId.HELLION,
    UnitTypeId.SIEGETANK,
    UnitTypeId.CYCLONE,
    UnitTypeId.THOR,
    UnitTypeId.VIKINGFIGHTER,
    UnitTypeId.MEDIVAC,
}


def state(frame, *, emergency: bool = False):
    believed = AwarenessModel().infer(frame)
    intent = StrategyModel().decide(frame, believed)
    return believed, replace(intent, emergency=emergency)


def shares(plan) -> dict[UnitTypeId, float]:
    return {unit_type: share for unit_type, share, _ in plan.units}


def resources(plan) -> dict[UnitTypeId, float]:
    return {unit_type: share for unit_type, share, _ in plan.mix}


def planned(style, enemy, *, ready=EVERYTHING, race=Race.Zerg, army=None, structures=()):
    frame = attention(tech_ready=ready, enemy_race=race, own_structures=structures)
    _, strategy = state(frame)
    return composition.CompositionPolicy(style).plan(frame, strategy, enemy, army=army)


@pytest.mark.parametrize("style", list(styles.STYLES.values()), ids=list(styles.STYLES))
def test_with_nothing_seen_the_mix_is_the_style(style) -> None:
    frame = attention(tech_ready={unit_type for unit_type, _, _ in style.composition})
    _, strategy = state(frame)

    plan = composition.CompositionPolicy(style).plan(frame, strategy)

    assert plan.units == style.composition
    assert plan.reason == "style_baseline"
    assert plan.doctrine == 1.0


def test_mech_has_no_marine_and_every_style_sums_to_one() -> None:
    assert UnitTypeId.MARINE not in {unit_type for unit_type, _, _ in styles.MECH.composition}
    assert UnitTypeId.MARINE not in styles.MECH.adds
    for style in styles.STYLES.values():
        assert sum(share for _, share, _ in style.composition) == pytest.approx(1.0)


def test_air_is_answered_by_what_hits_air_and_ground_units_give_way() -> None:
    plan = planned(styles.MECH, ((UnitTypeId.MUTALISK, 60.0),))

    mutalisk = next(item for item in plan.enemy if item.type_id is UnitTypeId.MUTALISK)
    answering = {unit_type for unit_type, _ in mutalisk.answers}
    assert answering <= {UnitTypeId.CYCLONE, UnitTypeId.THOR, UnitTypeId.VIKINGFIGHTER}
    assert answering
    doctrine = dict((unit_type, share) for unit_type, share, _ in styles.MECH.composition)
    assert shares(plan).get(UnitTypeId.HELLION, 0.0) < doctrine[UnitTypeId.HELLION]
    assert shares(plan).get(UnitTypeId.SIEGETANK, 0.0) < doctrine[UnitTypeId.SIEGETANK]
    assert plan.reason == "efficacy"
    assert sum(shares(plan).values()) == pytest.approx(1.0)


def test_the_mix_moves_continuously_with_what_is_seen() -> None:
    before = resources(planned(styles.BIO, ((UnitTypeId.ROACH, 30.0), (UnitTypeId.ZERGLING, 10.0))))
    after = resources(planned(styles.BIO, ((UnitTypeId.ROACH, 30.5), (UnitTypeId.ZERGLING, 10.0))))

    assert set(before) == set(after)
    assert max(abs(before[unit_type] - after[unit_type]) for unit_type in before) < 0.01


def test_the_more_is_seen_the_less_the_doctrine_weighs() -> None:
    config = composition.CompositionConfig(model_digest="unused")
    little = planned(styles.BIO, ((UnitTypeId.ROACH, 5.0),))
    much = planned(styles.BIO, ((UnitTypeId.ROACH, 200.0),))

    assert little.doctrine == pytest.approx(config.doctrine_power / (5.0 + config.doctrine_power))
    assert much.doctrine < little.doctrine
    doctrine = dict((unit_type, share) for unit_type, share, _ in styles.BIO.composition)
    gap = lambda plan: sum(abs(shares(plan).get(t, 0.0) - s) for t, s in doctrine.items())  # noqa: E731
    assert gap(much) > gap(little)


def test_the_mix_is_the_optimum_of_the_portfolio() -> None:
    """KKT: S g_i + D b_i / x_i = S + D for every type the mix uses."""

    policy = composition.CompositionPolicy(styles.MECH)
    shares_ = {UnitTypeId.MUTALISK: 0.5, UnitTypeId.ROACH: 0.3, UnitTypeId.ZERGLING: 0.2}
    availability = {unit_type: 1.0 for unit_type in policy._combat}
    seen = 40.0

    x, _ = policy._optimize(shares_, seen, availability)

    k, columns = policy._efficacy(policy._combat, shares_, availability)
    w = [shares_[type_id] for type_id in columns]
    strength = x @ k
    gradient = k @ ([share for share in w] / strength)
    doctrine = policy.config.doctrine_power
    for row, share in enumerate(x):
        if share > 1e-3:
            stationary = seen * gradient[row] + doctrine * policy._doctrine[row] / share
            assert stationary == pytest.approx(seen + doctrine, rel=1e-3)


def test_missing_tech_discounts_a_unit_by_the_time_it_takes() -> None:
    enemy = ((UnitTypeId.MUTALISK, 60.0),)
    without_thor = EVERYTHING - {UnitTypeId.THOR}
    ready = planned(styles.MECH, enemy)
    building = planned(
        styles.MECH,
        enemy,
        ready=without_thor,
        structures=(
            unit(100, UnitTypeId.BARRACKS, structure=True, power=0.0),
            unit(101, UnitTypeId.FACTORY, structure=True, power=0.0),
            unit(102, UnitTypeId.FACTORYTECHLAB, structure=True, power=0.0),
            unit(103, UnitTypeId.ARMORY, structure=True, power=0.0, ready=False),
        ),
    )
    missing = planned(
        styles.MECH,
        enemy,
        ready=without_thor,
        structures=(
            unit(100, UnitTypeId.BARRACKS, structure=True, power=0.0),
            unit(101, UnitTypeId.FACTORY, structure=True, power=0.0),
            unit(102, UnitTypeId.FACTORYTECHLAB, structure=True, power=0.0),
        ),
    )

    thor = lambda plan: resources(plan).get(UnitTypeId.THOR, 0.0)  # noqa: E731
    availability = lambda plan: next(a for t, _, a in plan.mix if t is UnitTypeId.THOR)  # noqa: E731
    assert thor(ready) > thor(building) > thor(missing)
    assert availability(ready) == 1.0
    assert availability(building) == pytest.approx(composition.math.exp(-23.0 / 60.0))
    assert availability(missing) == pytest.approx(composition.math.exp(-46.0 / 60.0))


def test_a_type_below_the_least_share_is_left_to_ares_to_ignore() -> None:
    plan = planned(styles.BIO, ((UnitTypeId.ZERGLING, 200.0),))

    assert all(share >= 0.05 for _, share, _ in plan.units)
    assert sum(shares(plan).values()) == pytest.approx(1.0)


def test_army_believed_beyond_what_was_seen_is_spread_by_the_prior() -> None:
    enemy = ((UnitTypeId.ZERGLING, 5.0),)
    seen_only = planned(styles.BIO, enemy)
    believed = planned(styles.BIO, enemy, army=EnemyArmyBelief(power=80.0, sigma=20.0))

    zergling = lambda plan: next(i.share for i in plan.enemy if i.type_id is UnitTypeId.ZERGLING)  # noqa: E731
    roach = lambda plan: next(i.share for i in plan.enemy if i.type_id is UnitTypeId.ROACH)  # noqa: E731
    assert believed.believed_power == pytest.approx(90.0)
    assert seen_only.believed_power == pytest.approx(5.0)
    assert zergling(believed) < zergling(seen_only)
    assert roach(believed) > roach(seen_only)
    assert sum(item.share for item in believed.enemy) == pytest.approx(1.0)


def test_an_unknown_race_believes_in_every_race_at_once() -> None:
    plan = planned(styles.BIO, ((UnitTypeId.MARINE, 1.0),), race=Race.Random)

    believed = {item.type_id for item in plan.enemy}
    assert {UnitTypeId.ZERGLING, UnitTypeId.STALKER, UnitTypeId.MARINE} <= believed


def test_modes_count_as_their_unit_and_unknown_types_are_reported() -> None:
    plan = planned(
        styles.BIO,
        (
            (UnitTypeId.SIEGETANKSIEGED, 10.0),
            (UnitTypeId.SIEGETANK, 2.0),
            (UnitTypeId.OVERSEER, 3.0),
        ),
        race=Race.Terran,
    )

    tank = next(item for item in plan.enemy if item.type_id is UnitTypeId.SIEGETANK)
    assert tank.seen == pytest.approx(12.0)
    assert plan.seen_power == pytest.approx(12.0)
    assert plan.unmodeled == ((UnitTypeId.OVERSEER, 3.0),)


def test_reactors_follow_what_the_structure_trains_without_a_tech_lab() -> None:
    assert composition.reactor_share(styles.MECH.composition, UnitTypeId.FACTORY) == pytest.approx(
        0.39 / (0.39 + 2 * (0.24 + 0.37))
    )
    assert composition.reactor_share(styles.BIO.composition, UnitTypeId.BARRACKS) == pytest.approx(
        0.55 / (0.55 + 2 * 0.2)
    )
    assert composition.reactor_share(styles.MECH.composition, UnitTypeId.STARPORT) == 0.0


def test_survive_uses_ready_barracks_and_the_fallback_leaves_with_the_policy() -> None:
    barracks = unit(100, UnitTypeId.BARRACKS, structure=True, power=0.0)
    factory = unit(101, UnitTypeId.FACTORY, structure=True, power=0.0)
    ling = unit(1, UnitTypeId.ZERGLING, x=10.5, y=10.5)
    frame = attention(
        own_structures=(barracks, factory),
        enemy_units=(ling,),
        tech_ready={UnitTypeId.MARINE, UnitTypeId.HELLION},
    )
    believed, survive = state(frame, emergency=True)
    policy = composition.CompositionPolicy(styles.MECH)

    emergency = policy.plan(
        frame,
        survive,
        believed.seen_enemy_types,
        army=believed.enemy_army,
        contacts=believed.contacts,
        incidents=believed.incidents,
    )
    normal = policy.plan(
        frame,
        replace(survive, emergency=False),
        believed.seen_enemy_types,
        army=believed.enemy_army,
        contacts=believed.contacts,
        incidents=believed.incidents,
    )

    assert emergency.reason == "survival_fallback"
    assert emergency.survival is not None
    assert UnitTypeId.MARINE in {unit_type for unit_type, _, _ in emergency.units}
    assert UnitTypeId.MARINE not in {unit_type for unit_type, _, _ in normal.units}
    # What hits Zerglings best per resource trains first.
    assert emergency.units[0][0] in {UnitTypeId.MARINE, UnitTypeId.HELLION}

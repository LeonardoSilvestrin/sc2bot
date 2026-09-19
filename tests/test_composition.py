from __future__ import annotations

from dataclasses import replace

import pytest
from sc2.ids.unit_typeid import UnitTypeId

from bot.awareness import AwarenessModel
from bot.ego.planners.economy.knowledge import styles
from bot.ego.planners.economy.policies import composition
from bot.ego.strategy import StrategyModel

from .fakes import attention, unit


def state(frame, *, emergency: bool = False):
    believed = AwarenessModel().infer(frame)
    intent = StrategyModel().decide(frame, believed)
    return believed, replace(intent, emergency=emergency)


def shares(plan) -> dict[UnitTypeId, float]:
    return {unit_type: share for unit_type, share, _ in plan.units}


@pytest.mark.parametrize("style", list(styles.STYLES.values()), ids=list(styles.STYLES))
def test_with_nothing_seen_the_mix_is_the_style(style) -> None:
    frame = attention(tech_ready={unit_type for unit_type, _, _ in style.composition})
    _, strategy = state(frame)

    plan = composition.CompositionPolicy(style).plan(frame, strategy)

    assert plan.units == style.composition
    assert plan.reason == "style_baseline"


def test_mech_has_no_marine_and_every_style_sums_to_one() -> None:
    assert UnitTypeId.MARINE not in {unit_type for unit_type, _, _ in styles.MECH.composition}
    for style in styles.STYLES.values():
        assert sum(share for _, share, _ in style.composition) == pytest.approx(1.0)


def test_the_first_producible_counter_is_selected_and_skipped_tech_is_explained() -> None:
    frame = attention(tech_ready={UnitTypeId.MARINE, UnitTypeId.CYCLONE})
    _, strategy = state(frame)

    plan = composition.CompositionPolicy(styles.MECH).plan(
        frame, strategy, ((UnitTypeId.MUTALISK, 40.0),)
    )

    adaptation = plan.adaptations[0]
    assert adaptation.response is UnitTypeId.MARINE
    assert adaptation.skipped == ((UnitTypeId.THOR, "tech_missing"),)
    assert UnitTypeId.MARINE in shares(plan)
    assert plan.reason == "counter_adaptation"


def test_new_tech_moves_the_same_threat_to_the_preferred_counter() -> None:
    frame = attention(tech_ready={UnitTypeId.MARINE, UnitTypeId.THOR})
    _, strategy = state(frame)

    plan = composition.CompositionPolicy(styles.MECH).plan(
        frame, strategy, ((UnitTypeId.MUTALISK, 40.0),)
    )

    assert plan.adaptations[0].response is UnitTypeId.THOR
    # Supply mixing prevents a six-supply Thor from being treated as one Marine.
    assert 0.0 < shares(plan)[UnitTypeId.THOR] < 0.5
    assert sum(shares(plan).values()) == pytest.approx(1.0)


def test_no_producible_counter_keeps_a_normalized_baseline() -> None:
    frame = attention()
    _, strategy = state(frame)

    plan = composition.CompositionPolicy(styles.BIO).plan(
        frame, strategy, ((UnitTypeId.MUTALISK, 40.0),)
    )

    assert plan.adaptations[0].status == "no_producible_counter"
    assert shares(plan) == pytest.approx(
        {unit_type: share for unit_type, share, _ in styles.BIO.composition}
    )
    assert sum(shares(plan).values()) == pytest.approx(1.0)


def test_modes_are_canonicalized_but_preserved_in_the_explanation() -> None:
    frame = attention(tech_ready={UnitTypeId.MARAUDER})
    _, strategy = state(frame)

    plan = composition.CompositionPolicy(styles.BIO).plan(
        frame, strategy, ((UnitTypeId.SIEGETANKSIEGED, 10.0),)
    )

    assert plan.enemy == ((UnitTypeId.SIEGETANKSIEGED, UnitTypeId.SIEGETANK, 10.0),)
    assert plan.adaptations[0].response is UnitTypeId.MARAUDER


def test_a_mode_keeps_its_physical_layer_after_catalog_canonicalization() -> None:
    frame = attention(tech_ready={UnitTypeId.HELLION, UnitTypeId.MARINE})
    _, strategy = state(frame)

    plan = composition.CompositionPolicy(styles.MECH).plan(
        frame, strategy, ((UnitTypeId.LOCUSTMPFLYING, 10.0),)
    )

    assert plan.adaptations[0].response is UnitTypeId.MARINE
    assert plan.adaptations[0].skipped == ((UnitTypeId.HELLION, "cannot_reach"),)


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
        contacts=believed.contacts,
        incidents=believed.incidents,
    )
    normal = policy.plan(
        frame,
        replace(survive, emergency=False),
        believed.seen_enemy_types,
        contacts=believed.contacts,
        incidents=believed.incidents,
    )

    assert emergency.reason == "survival_fallback"
    assert emergency.survival is not None
    assert UnitTypeId.MARINE in {unit_type for unit_type, _, _ in emergency.units}
    assert UnitTypeId.MARINE not in {unit_type for unit_type, _, _ in normal.units}


@pytest.mark.parametrize("style", list(styles.STYLES.values()), ids=list(styles.STYLES))
def test_every_style_unit_knows_what_it_can_shoot(style) -> None:
    for unit_type, _, _ in style.composition:
        assert unit_type in composition.REACH

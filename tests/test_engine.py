from __future__ import annotations

from dataclasses import replace

import pytest
from sc2.ids.unit_typeid import UnitTypeId

from bot.body.engine import Engine, GrantStatus, rank
from bot.ego.planners import Domain

from .fakes import attention, proposal, unit


def test_proposals_rank_by_priority_then_owner_then_id() -> None:
    proposals = (
        proposal("core_army", 0.0),
        proposal("defense:b", 0.5),
        proposal("defense:a", 0.5),
        proposal("alpha:z", 0.5),
        proposal("defense:c", 0.9),
    )

    assert [item.proposal_id for item in rank(proposals)] == [
        "defense:c",
        "alpha:z",
        "defense:a",
        "defense:b",
        "core_army",
    ]


def test_each_unit_is_granted_once_nearest_first_and_the_fallback_takes_the_rest() -> None:
    army = (unit(1, x=29, y=30), unit(2, x=20, y=30), unit(3, x=25, y=30), unit(4, x=10, y=10))
    frame = attention(
        own_units=(
            *army,
            unit(9, UnitTypeId.SCV, 30, 30, worker=True),
            unit(8, UnitTypeId.MULE, 30, 30, worker=True),
            unit(7, UnitTypeId.BARRACKS, 30, 30, power=0.0, structure=True),
        )
    )

    result = Engine().allocate(
        frame, (proposal("core_army", 0.0), proposal("defense:main", 0.4, count=2))
    )

    defense, core = result.grants
    assert defense.proposal.proposal_id == "defense:main"
    assert defense.tags == (1, 3)
    assert core.tags == (2, 4)
    assert result.unassigned == ()
    assert dict(result.owners) == {
        1: "defense:main",
        2: "core_army",
        3: "defense:main",
        4: "core_army",
    }


def test_unit_types_restrict_who_a_proposal_can_take() -> None:
    frame = attention(own_units=(unit(1, x=30, y=30), unit(2, UnitTypeId.MARAUDER, 30, 30)))

    result = Engine().allocate(
        frame,
        (
            proposal("defense:air", 1.0, unit_types=frozenset({UnitTypeId.MARINE})),
            proposal("core_army", 0.0),
        ),
    )

    assert result.grants[0].tags == (1,)
    assert result.grants[1].tags == (2,)


def test_a_grant_keeps_its_units_while_they_move() -> None:
    engine = Engine()
    engine.allocate(
        attention(own_units=(unit(1, x=29, y=30), unit(2, x=10, y=10))),
        (proposal("defense:main", 1.0, count=1),),
    )

    moved = attention(own_units=(unit(1, x=15, y=15), unit(2, x=28, y=30)))
    result = engine.allocate(moved, (proposal("defense:main", 1.0, count=1),))

    assert result.grants[0].tags == (1,)


def test_units_no_proposal_holds_any_more_are_released() -> None:
    engine = Engine()
    first = engine.allocate(
        attention(own_units=(unit(1, x=29, y=30), unit(2, x=10, y=10))),
        (proposal("defense:main", 1.0),),
    )
    assert first.released == ()

    result = engine.allocate(attention(own_units=(unit(2, x=10, y=10),)), ())

    assert result.released == (1, 2)
    assert result.unassigned == (2,)


def test_a_power_demand_takes_the_nearest_units_until_it_is_met() -> None:
    frame = attention(
        own_units=(
            unit(1, x=29, y=30),
            unit(2, UnitTypeId.SIEGETANK, 27, 30, power=2.8, attack_air=False),
            unit(3, UnitTypeId.MEDIVAC, 30, 30, power=0.0),
            unit(4, x=10, y=10),
        )
    )
    demand = replace(proposal("defense:x", 1.0), minimum_power=3.0)

    grant, core = Engine().allocate(frame, (demand, proposal("core_army", 0.0))).grants

    # The Medivac is nearest but adds no power; the Marine alone is not enough.
    assert grant.tags == (1, 2)
    assert grant.power == pytest.approx(3.8)
    assert (grant.status, grant.reason) == (GrantStatus.FULL, "minimum_power_met")
    assert core.tags == (3, 4)
    assert (core.status, core.reason) == (GrantStatus.FULL, "every_free_unit")


def test_a_grant_says_whether_it_got_what_it_asked_for_and_why() -> None:
    frame = attention(
        own_units=(
            unit(1, x=30, y=30),
            unit(2, UnitTypeId.MARAUDER, 31, 30, power=1.6, attack_air=False),
        )
    )
    proposals = (
        replace(proposal("a:air", 3.0), minimum_power=1.0, must_attack=Domain.AIR),
        replace(proposal("b:air", 2.0), minimum_power=1.0, must_attack=Domain.AIR),
        replace(proposal("c:ground", 1.0), minimum_power=5.0, must_attack=Domain.GROUND),
        proposal("d:scout", 0.5, count=1, unit_types=frozenset({UnitTypeId.SCV})),
    )

    result = Engine().allocate(frame, proposals)

    assert [(g.proposal.proposal_id, g.tags, g.status, g.reason) for g in result.grants] == [
        ("a:air", (1,), GrantStatus.FULL, "minimum_power_met"),
        ("b:air", (), GrantStatus.REJECTED, "eligible_units_taken"),
        ("c:ground", (2,), GrantStatus.PARTIAL, "insufficient_power"),
        ("d:scout", (), GrantStatus.REJECTED, "no_eligible_units"),
    ]


def test_a_duplicate_proposal_id_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        Engine().allocate(attention(), (proposal("defense:a", 1.0), proposal("defense:a", 0.5)))

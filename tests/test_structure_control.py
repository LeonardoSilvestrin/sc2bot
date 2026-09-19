from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from ares.consts import BuildingSize
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import read_map, unit_view
from bot.body.behaviors import structure_control as structure_behavior
from bot.ego.planners import StructurePlan
from bot.ego.planners.structure_control import RelocationConfig
from bot.ego.planners.structure_control.planner import StructureConfig, StructureControl
from bot.logs import Logs

from .fakes import MAP, FakeBot, FakeLogger, FakeUnit, attention, unit

REACH = StructureConfig().raise_reach
LOWER_AFTER = StructureConfig().lower_after


def depot(tag: int, x: float = 20.0, y: float = 20.0, *, lowered=False, ready=True):
    type_id = UnitTypeId.SUPPLYDEPOTLOWERED if lowered else UnitTypeId.SUPPLYDEPOT
    return unit(tag, type_id, x, y, power=0.0, structure=True, ready=ready)


def zergling(tag: int, x: float, y: float):
    return unit(tag, UnitTypeId.ZERGLING, x, y, attack_air=False)


def test_a_raised_depot_goes_down_with_no_enemy_near() -> None:
    plan = StructureControl().plan(attention(own_structures=(depot(1),)))

    assert (plan.lower, plan.raise_, plan.reason) == ((1,), (), "no_enemy_near")


def test_a_lowered_depot_rises_when_a_ground_enemy_comes_within_reach() -> None:
    # Only raised depots used to be planned, so a lowered one never rose again.
    frame = attention(
        own_structures=(depot(1, 20, 20, lowered=True), depot(2, 40, 40, lowered=True)),
        enemy_units=(zergling(90, 20 + REACH, 20),),
    )

    plan = StructureControl().plan(frame)

    assert (plan.lower, plan.raise_, plan.reason) == ((), (1,), "enemy_near")
    inputs = dict(plan.inputs)
    assert (inputs["depots"], inputs["lowered"], inputs["enemy_near"]) == (2.0, 2.0, 1.0)
    assert inputs["nearest_ground_enemy"] == pytest.approx(REACH)


def test_a_raised_depot_near_a_ground_enemy_stays_up() -> None:
    frame = attention(own_structures=(depot(1),), enemy_units=(zergling(90, 24, 20),))

    plan = StructureControl().plan(frame)

    assert (plan.lower, plan.raise_, plan.reason) == ((), (), "enemy_near")


def test_flying_and_distant_enemies_do_not_raise_a_depot() -> None:
    frame = attention(
        own_structures=(depot(1, 20, 20, lowered=True),),
        enemy_units=(
            unit(90, UnitTypeId.OVERLORD, 20, 20, power=0.0, flying=True),
            zergling(91, 20 + REACH + 0.5, 20),
        ),
    )

    plan = StructureControl().plan(frame)

    assert (plan.lower, plan.raise_, plan.reason) == ((), (), "no_enemy_near")


def test_a_depot_goes_down_lower_after_seconds_after_the_enemy_left() -> None:
    control = StructureControl()
    near = attention(
        time=10.0, own_structures=(depot(1, lowered=True),), enemy_units=(zergling(90, 22, 20),)
    )
    assert control.plan(near).raise_ == (1,)

    held = control.plan(attention(time=10.0 + LOWER_AFTER - 0.1, own_structures=(depot(1),)))
    cleared = control.plan(attention(time=10.0 + LOWER_AFTER, own_structures=(depot(1),)))

    assert (held.lower, held.reason) == ((), "enemy_recently_near")
    assert dict(held.inputs)["recently_near"] == 1.0
    assert (cleared.lower, cleared.reason) == ((1,), "no_enemy_near")


def test_an_enemy_pacing_across_the_edge_of_reach_does_not_toggle_the_depot() -> None:
    control = StructureControl()
    lowered = True
    orders: list[tuple[float, str]] = []
    # Frames every 0.25 s for 20 s. Until 10 s the Zergling is inside reach for
    # 0.5 s and outside for 0.5 s, last inside at 9.25 s; then it is gone.
    for index in range(81):
        now = index * 0.25
        pacing = now < 10.0
        inside = int(now / 0.5) % 2 == 0
        x = 20 + REACH + (-1.0 if inside else 1.0)
        frame = attention(
            time=now,
            own_structures=(depot(1, lowered=lowered),),
            enemy_units=(zergling(90, x, 20),) if pacing else (),
        )
        plan = control.plan(frame)
        if plan.raise_:
            orders.append((now, "raise"))
            lowered = False
        if plan.lower:
            orders.append((now, "lower"))
            lowered = True

    assert orders == [(0.0, "raise"), (9.25 + LOWER_AFTER, "lower")]


def test_raising_counts_our_ground_units_it_pushes_off_the_depot() -> None:
    frame = attention(
        own_units=(
            unit(5, x=20.5, y=20),
            unit(6, x=23, y=20),
            unit(7, UnitTypeId.MEDIVAC, 20, 20, flying=True),
        ),
        own_structures=(depot(1, lowered=True),),
        enemy_units=(zergling(90, 25, 20),),
    )

    plan = StructureControl().plan(frame)

    assert plan.raise_ == (1,)
    assert dict(plan.inputs)["friendly_on_raising"] == 1.0


def test_unfinished_depots_are_left_alone() -> None:
    frame = attention(
        own_structures=(depot(1, ready=False),), enemy_units=(zergling(90, 21, 20),)
    )

    plan = StructureControl().plan(frame)

    assert (plan.lower, plan.raise_, plan.reason) == ((), (), "no_depots")


@pytest.mark.parametrize("values", [{"raise_reach": 0.0}, {"lower_after": -1.0}])
def test_the_config_rejects_impossible_values(values) -> None:
    with pytest.raises(ValueError):
        StructureConfig(**values)


def test_the_behavior_orders_only_the_planned_depots() -> None:
    bot = FakeBot()
    bot.structures = [
        FakeUnit(1, UnitTypeId.SUPPLYDEPOT, 20, 20, dps=0.0, structure=True),
        FakeUnit(2, UnitTypeId.SUPPLYDEPOTLOWERED, 30, 30, dps=0.0, structure=True),
        FakeUnit(3, UnitTypeId.SUPPLYDEPOT, 40, 40, dps=0.0, structure=True),
    ]

    structure_behavior.execute(bot, StructurePlan(lower=(1,), raise_=(2,), reason="test"))

    assert [structure.commands for structure in bot.structures] == [
        [AbilityId.MORPH_SUPPLYDEPOT_LOWER],
        [AbilityId.MORPH_SUPPLYDEPOT_RAISE],
        [],
    ]


# --- Relocation: a Siege Tank walled in by our own production ----------------

RELOCATION = RelocationConfig()
TANK_AT = (30.5, 35.5)
# Far north of the Tank, through the one-cell gap between Barracks 10 and 11.
TANK_TO = (30.5, 50.5)
# Where the Tank stands once it got through; it has arrived and parks there.
THROUGH = (30.5, 38.0)
# Production sites of the main. From the Barracks 10, the site under the
# Factory is nearest, then the free one, then the farther one.
ON_THE_WAY = Point2((30.5, 44.5))
UNDER_FACTORY = Point2((22.5, 38.5))
FREE = Point2((22.5, 32.5))
FARTHER = Point2((40.5, 30.5))
IN_THE_CORRIDOR = Point2((14.5, 14.5))
SITES = (IN_THE_CORRIDOR, UNDER_FACTORY, FREE, ON_THE_WAY, FARTHER)
SITE_MAP = replace(MAP, production_sites=SITES)
FLYING = {
    UnitTypeId.BARRACKS: UnitTypeId.BARRACKSFLYING,
    UnitTypeId.FACTORY: UnitTypeId.FACTORYFLYING,
    UnitTypeId.STARPORT: UnitTypeId.STARPORTFLYING,
}


def tank(tag: int = 300, at=TANK_AT, to=TANK_TO, *, sieged: bool = False):
    type_id = UnitTypeId.SIEGETANKSIEGED if sieged else UnitTypeId.SIEGETANK
    return unit(tag, type_id, *at, power=3.0, moving_to=to)


def through():
    return tank(at=THROUGH, to=None)


def production(
    tag: int,
    x: float,
    y: float,
    type_id: UnitTypeId = UnitTypeId.BARRACKS,
    *,
    flying: bool = False,
    add_on: bool = False,
):
    return unit(
        tag,
        FLYING[type_id] if flying else type_id,
        x,
        y,
        power=0.0,
        structure=True,
        flying=flying,
        add_on=add_on,
    )


# Barracks 10 and 11 flank the gap the Tank cannot fit through; the Factory
# stands on a production site.
LEFT = production(10, 28.5, 38.5)
LEFT_FLYING = production(10, 28.5, 38.5, flying=True)
RIGHT = production(11, 32.5, 38.5)
FACTORY = production(12, *UNDER_FACTORY, UnitTypeId.FACTORY)


def walled(time: float, *units, structures=(LEFT, RIGHT, FACTORY), **values):
    return attention(
        time=time,
        own_units=units or (tank(),),
        own_structures=structures,
        map_view=SITE_MAP,
        **values,
    )


def transitions(plan) -> list[tuple[str, str]]:
    return [(event.transition, event.reason) for event in plan.relocation]


def stuck_at(control: StructureControl, **values):
    """The walled Tank from 0 s, a frame a second, to the frame it is stuck."""

    frames = [float(second) for second in range(int(RELOCATION.stuck_after) + 1)]
    plans = [control.plan(walled(now, **values)) for now in frames]
    assert all(not plan.relocation and not plan.lift for plan in plans[:-1])
    return plans[-1]


def test_a_tank_ordered_away_that_does_not_move_is_stuck_after_stuck_after() -> None:
    control = StructureControl()
    before = [control.plan(walled(now)) for now in (0.0, 1.0, 2.0, 3.0, 3.9)]

    stuck = control.plan(walled(RELOCATION.stuck_after))
    after = control.plan(walled(RELOCATION.stuck_after + 0.5))

    assert all(not plan.relocation and not plan.lift for plan in before)
    event = stuck.relocation[0]
    assert (event.transition, event.tank) == ("tank_stuck", 300)
    assert dict(event.inputs)["stuck_for"] == pytest.approx(RELOCATION.stuck_after)
    # Once per episode.
    assert after.relocation == ()


@pytest.mark.parametrize(
    "tank_at",
    [
        # Walking: a step longer than `progress_distance` every second.
        lambda now: tank(at=(30.5, 20.0 + 2.0 * now)),
        # Parked: no order.
        lambda now: tank(to=None),
        # Waiting at its point: the order is within `arrive_distance`.
        lambda now: tank(to=(30.5, 37.5)),
        lambda now: tank(to=None, sieged=True),
    ],
    ids=["walking", "idle", "at_its_point", "sieged"],
)
def test_a_tank_walking_parked_waiting_or_sieged_is_never_stuck(tank_at) -> None:
    control = StructureControl()

    plans = [control.plan(walled(float(now), tank_at(now))) for now in range(12)]

    assert all(not plan.relocation and not plan.lift for plan in plans)


def test_a_tank_with_an_enemy_near_is_fighting_not_stuck() -> None:
    control = StructureControl()

    plans = [
        control.plan(walled(float(now), enemy_units=(zergling(90, 30.5, 45.0),)))
        for now in range(12)
    ]

    assert all(not plan.relocation and not plan.lift for plan in plans)


def test_a_tank_that_loses_its_order_for_a_moment_is_still_stuck() -> None:
    # The game drops an order it cannot path; the behavior orders it again.
    control = StructureControl()
    for now in (0.0, 1.0, 2.0):
        control.plan(walled(now))
    control.plan(walled(2.5, tank(to=None)))

    plan = control.plan(walled(RELOCATION.stuck_after))

    assert transitions(plan)[0] == ("tank_stuck", "blocker_selected")


def test_the_tank_moving_again_clears_its_track() -> None:
    control = StructureControl()
    for now in (0.0, 1.0, 2.0, 3.0):
        control.plan(walled(now))
    # It gets through, then is held again further on: the clock starts over.
    control.plan(walled(3.5, tank(at=THROUGH)))

    held = [control.plan(walled(now, tank(at=THROUGH))) for now in (4.0, 7.0)]
    stuck = control.plan(walled(7.5, tank(at=THROUGH)))

    assert all(not plan.relocation for plan in held)
    assert transitions(stuck)[0][0] == "tank_stuck"


def test_the_blocker_is_one_production_structure_ahead_of_the_tank() -> None:
    plan = stuck_at(StructureControl())

    # Both Barracks are in the way; exactly one lifts, the lower tag on a tie.
    assert plan.lift == (10,)
    assert transitions(plan) == [
        ("tank_stuck", "blocker_selected"),
        ("blocker_selected", "no_add_on"),
        ("lifting", "lift_ordered"),
    ]
    selected = plan.relocation[1]
    assert (selected.tank, selected.structure) == (300, 10)
    assert dict(selected.inputs)["candidates"] == 2.0


def test_the_blocker_without_an_add_on_goes_first_even_if_farther() -> None:
    near_with_reactor = production(10, 28.5, 38.5, add_on=True)
    farther_without = production(11, 33.0, 38.5)

    plan = stuck_at(StructureControl(), structures=(near_with_reactor, farther_without))

    assert plan.lift == (11,)
    assert plan.relocation[1].reason == "no_add_on"


def test_a_structure_with_an_add_on_lifts_when_it_is_the_only_blocker() -> None:
    plan = stuck_at(StructureControl(), structures=(production(10, 28.5, 38.5, add_on=True),))

    assert plan.lift == (10,)
    assert plan.relocation[1].reason == "with_add_on"


@pytest.mark.parametrize(
    "structures",
    [
        (production(10, 30.5, 32.5),),
        (production(10, 35.5, 38.5),),
        (production(10, 30.5, 45.5),),
        (unit(10, UnitTypeId.COMMANDCENTER, 30.5, 40.0, power=0.0, structure=True),),
        (
            depot(10, 30.5, 37.5),
            unit(11, UnitTypeId.BARRACKS, 28.5, 38.5, power=0.0, structure=True, ready=False),
        ),
    ],
    ids=["behind", "aside", "far_ahead", "command_center", "depot_and_unfinished"],
)
def test_nothing_else_is_a_blocker(structures) -> None:
    plan = stuck_at(StructureControl(), structures=structures)

    assert plan.lift == ()
    assert transitions(plan) == [("tank_stuck", "no_blocker")]


def run_relocation(control: StructureControl) -> dict:
    """From the lift at 4 s to the landing at 12 s: the plan of every step."""

    plans = {"lift": stuck_at(control)}
    walled_in = (LEFT_FLYING, RIGHT, FACTORY)
    plans["lifted"] = control.plan(walled(5.0, structures=walled_in))
    plans["waiting"] = control.plan(walled(6.0, structures=walled_in))
    plans["moving"] = control.plan(walled(7.0, through(), structures=walled_in))
    plans["flying"] = control.plan(walled(8.0, through(), structures=walled_in))
    near = production(10, 26.0, 36.0, flying=True)
    plans["landing"] = control.plan(walled(9.0, through(), structures=(near, RIGHT, FACTORY)))
    landed = production(10, *FREE)
    plans["landed"] = control.plan(walled(12.0, through(), structures=(landed, RIGHT, FACTORY)))
    return plans


def test_the_lifted_structure_lands_only_once_the_tank_moves_off_its_way() -> None:
    plans = run_relocation(StructureControl())

    assert [transitions(plans[step]) for step in ("lifted", "waiting")] == [[], []]
    assert all(not plans[step].land for step in ("lift", "lifted", "waiting"))
    assert transitions(plans["moving"]) == [
        ("tank_moving", "land_after"),
        ("relocating", "site_found"),
    ]
    # Nearest the origin, off the Tank's way and the ramp corridor, not taken.
    assert plans["moving"].land == ((10, FREE),)
    assert plans["moving"].relocation[1].site == FREE
    assert not plans["flying"].land and not plans["flying"].relocation
    assert transitions(plans["landing"]) == [("landing", "at_site")]
    assert transitions(plans["landed"]) == [("relocation_complete", "landed")]
    assert plans["landed"].relocation[0].site == FREE
    # Nothing is lifted or landed twice.
    assert sum(len(plan.lift) for plan in plans.values()) == 1
    assert sum(len(plan.land) for plan in plans.values()) == 1


def test_a_tank_that_stays_stuck_lets_the_structure_land_after_wait_timeout() -> None:
    control = StructureControl()
    stuck_at(control)
    walled_in = (LEFT_FLYING, RIGHT, FACTORY)
    control.plan(walled(5.0, structures=walled_in))

    held = control.plan(walled(5.0 + RELOCATION.wait_timeout - 0.1, structures=walled_in))
    landed = control.plan(walled(5.0 + RELOCATION.wait_timeout, structures=walled_in))

    assert not held.relocation and not held.land
    assert transitions(landed)[0] == ("tank_still_stuck", "land_after")
    assert landed.land == ((10, FREE),)


def test_a_tank_that_sieges_or_dies_meanwhile_lets_the_structure_land() -> None:
    control = StructureControl()
    stuck_at(control)
    walled_in = (LEFT_FLYING, RIGHT, FACTORY)
    control.plan(walled(5.0, structures=walled_in))

    plan = control.plan(walled(6.0, tank(to=None, sieged=True), structures=walled_in))

    assert transitions(plan) == [("tank_gone", "land_after"), ("relocating", "site_found")]
    assert dict(plan.relocation[0].inputs) == {"waited": 1.0}
    assert plan.land == ((10, FREE),)


def test_with_no_free_site_the_structure_keeps_flying_and_looks_again_later() -> None:
    control = StructureControl()
    stuck_at(control)
    on_free = production(13, *FREE, UnitTypeId.STARPORT)
    on_farther = production(14, *FARTHER, UnitTypeId.STARPORT)
    full = (LEFT_FLYING, RIGHT, FACTORY, on_free, on_farther)
    freed = (LEFT_FLYING, RIGHT, FACTORY, on_farther)
    control.plan(walled(5.0, structures=full))

    none = control.plan(walled(6.0, through(), structures=full))
    # It looks again at 11 s, and finds nothing either.
    quiet = [control.plan(walled(now, through(), structures=full)) for now in (7.0, 11.0, 12.0)]
    # The Starport on the free site has left; the next look is at 16 s.
    early = control.plan(walled(15.9, through(), structures=freed))
    found = control.plan(walled(16.0, through(), structures=freed))

    assert transitions(none) == [
        ("tank_moving", "land_after"),
        ("no_landing_site", "keep_flying"),
    ]
    assert not none.land
    assert all(not plan.relocation and not plan.land for plan in quiet)
    assert not early.land and not early.relocation
    assert found.land == ((10, FREE),)
    assert transitions(found) == [("relocating", "site_found")]


def test_a_site_it_cannot_land_on_in_land_timeout_is_dropped_for_the_next() -> None:
    control = StructureControl()
    stuck_at(control)
    walled_in = (LEFT_FLYING, RIGHT, FACTORY)
    control.plan(walled(5.0, structures=walled_in))
    first = control.plan(walled(6.0, through(), structures=walled_in))

    held = control.plan(walled(6.0 + RELOCATION.land_timeout, through(), structures=walled_in))
    retry = control.plan(walled(6.1 + RELOCATION.land_timeout, through(), structures=walled_in))

    assert first.land == ((10, FREE),)
    assert not held.land
    assert retry.land == ((10, FARTHER),)
    assert transitions(retry) == [("relocating", "retry")]


def test_a_structure_that_does_not_lift_is_given_up_after_lift_timeout() -> None:
    control = StructureControl()
    stuck_at(control)

    held = control.plan(walled(RELOCATION.stuck_after + RELOCATION.lift_timeout))
    given_up = control.plan(walled(RELOCATION.stuck_after + RELOCATION.lift_timeout + 0.1))

    assert not held.relocation
    assert transitions(given_up) == [("relocation_aborted", "lift_failed")]


def test_a_structure_lost_on_the_way_ends_the_relocation() -> None:
    control = StructureControl()
    stuck_at(control)

    plan = control.plan(walled(5.0, structures=(RIGHT, FACTORY)))

    assert transitions(plan) == [("relocation_aborted", "structure_lost")]


def test_a_relocation_starts_only_after_the_global_cooldown() -> None:
    control = StructureControl()
    run_relocation(control)
    done = 12.0
    # Another Tank, walled in between the Barracks 11 and 15.
    other = tank(301, at=(34.5, 35.5), to=(34.5, 50.5))
    structures = (production(10, *FREE), RIGHT, FACTORY, production(15, 36.5, 38.5))

    frames = [done + step for step in range(int(RELOCATION.global_cooldown))]
    waiting = [control.plan(walled(now, other, structures=structures)) for now in frames]
    ready = control.plan(walled(done + RELOCATION.global_cooldown, other, structures=structures))

    assert all(not plan.lift for plan in waiting)
    assert [t for plan in waiting for t in transitions(plan)] == [("tank_stuck", "cooldown")]
    assert ready.lift == (11,)


def test_a_relocated_structure_is_not_lifted_again_before_its_cooldown() -> None:
    control = StructureControl()
    run_relocation(control)
    # Somehow back in the way of a Tank, alone.
    back = (LEFT,)
    lifted_at = RELOCATION.stuck_after
    again = lifted_at + RELOCATION.structure_cooldown

    early = [control.plan(walled(float(now), structures=back)) for now in range(40, int(again))]
    late = control.plan(walled(again, structures=back))

    assert all(not plan.lift for plan in early)
    assert ("tank_stuck", "no_blocker") in [t for plan in early for t in transitions(plan)]
    assert late.lift == (10,)


def test_one_relocation_at_a_time() -> None:
    control = StructureControl()
    # A second Tank, walled in elsewhere by a Barracks of its own.
    second = tank(301, at=(50.5, 35.5), to=(50.5, 50.5))
    elsewhere = production(13, 48.5, 38.5)

    walled_in = (LEFT, RIGHT, FACTORY, elsewhere)
    lifted = (LEFT_FLYING, RIGHT, FACTORY, elsewhere)

    first = [
        control.plan(walled(float(now), tank(), second, structures=walled_in))
        for now in range(5)
    ]
    during = [
        control.plan(walled(float(now), tank(), second, structures=lifted))
        for now in range(5, 12)
    ]

    assert [plan.lift for plan in first] == [(), (), (), (), (10,)]
    assert transitions(first[-1])[:2] == [
        ("tank_stuck", "blocker_selected"),
        ("tank_stuck", "relocation_active"),
    ]
    assert all(not plan.lift for plan in during)


def test_the_ramp_corridor_is_the_sites_along_the_way_from_the_start_to_the_ramp() -> None:
    assert StructureControl().corridor(SITE_MAP) == (IN_THE_CORRIDOR,)


@pytest.mark.parametrize(
    "values", [{"stuck_after": 0.0}, {"progress_distance": -1.0}, {"lane": -0.5}]
)
def test_the_relocation_config_rejects_impossible_values(values) -> None:
    with pytest.raises(ValueError):
        RelocationConfig(**values)


# --- The depots do not notice the relocation ---------------------------------


def test_the_depots_plan_the_same_with_a_relocation_running() -> None:
    def run(*, relocating: bool) -> list[StructurePlan]:
        control = StructureControl()
        plans = []
        for index in range(40):
            now = index * 0.5
            near = now < 8.0
            structures = (depot(1, 20, 20, lowered=not near), depot(2, 40, 12))
            units = ()
            if relocating:
                structures += (LEFT_FLYING if now > 5.0 else LEFT, RIGHT, FACTORY)
                units = (tank(at=THROUGH) if now > 7.0 else tank(),)
            frame = attention(
                time=now,
                own_units=units,
                own_structures=structures,
                enemy_units=(zergling(90, 24, 20),) if near else (),
                map_view=SITE_MAP,
            )
            plans.append(control.plan(frame))
        return plans

    plain = run(relocating=False)
    busy = run(relocating=True)

    assert [(p.lower, p.raise_, p.reason, p.inputs) for p in busy] == [
        (p.lower, p.raise_, p.reason, p.inputs) for p in plain
    ]
    assert any(plan.lift for plan in busy) and any(plan.land for plan in busy)


def test_the_behavior_lifts_and_lands_beside_the_depots() -> None:
    bot = FakeBot()
    bot.structures = [
        FakeUnit(1, UnitTypeId.SUPPLYDEPOT, 20, 20, dps=0.0, structure=True),
        FakeUnit(2, UnitTypeId.SUPPLYDEPOTLOWERED, 30, 30, dps=0.0, structure=True),
        FakeUnit(10, UnitTypeId.BARRACKS, 28.5, 38.5, dps=0.0, structure=True),
        FakeUnit(11, UnitTypeId.FACTORYFLYING, 40, 40, dps=0.0, structure=True, flying=True),
        FakeUnit(12, UnitTypeId.STARPORT, 50.5, 50.5, dps=0.0, structure=True),
    ]
    plan = StructurePlan(lower=(1,), raise_=(2,), lift=(10,), land=((11, FREE),), reason="test")

    structure_behavior.execute(bot, plan)

    assert [structure.commands for structure in bot.structures] == [
        [AbilityId.MORPH_SUPPLYDEPOT_LOWER],
        [AbilityId.MORPH_SUPPLYDEPOT_RAISE],
        # What it trains is cancelled first: a busy structure cannot lift.
        [AbilityId.CANCEL_QUEUE5, ("queue", AbilityId.LIFT)],
        [],
        [],
    ]
    assert bot.mediator.moved_structures == [(11, FREE, True)]


# --- What Attention and Ares' placement give it ------------------------------


def test_attention_reads_where_a_unit_walks_to_and_whether_it_has_an_add_on() -> None:
    def order(ability: AbilityId, target):
        return SimpleNamespace(ability=SimpleNamespace(id=ability), target=target)

    def view(*orders, add_on=False):
        fake = FakeUnit(1, UnitTypeId.SIEGETANK, 30, 30)
        fake.orders = list(orders)
        fake.has_add_on = add_on
        return unit_view(fake, lambda _type: 3.0)

    to = Point2(TANK_TO)

    assert view(order(AbilityId.MOVE, to)).moving_to == to
    assert view(order(AbilityId.ATTACK, to)).moving_to == to
    # Attacking a unit, sieging, or nothing at all is not walking.
    assert view(order(AbilityId.ATTACK, 900)).moving_to is None
    assert view(order(AbilityId.SIEGEMODE_SIEGEMODE, None)).moving_to is None
    assert view().moving_to is None
    assert view(add_on=True).has_add_on and not view().has_add_on


def placements(*sites, wall=()) -> dict:
    return {
        MAP.own_start: {
            BuildingSize.THREE_BY_THREE: {
                site: {"available": True, "is_wall": site in wall} for site in (*sites, *wall)
            }
        }
    }


def test_read_map_reads_the_main_production_sites_without_the_wall() -> None:
    bot = FakeBot()
    bot.mediator.get_placements_dict = placements(FARTHER, FREE, wall=(Point2((17.5, 15.5)),))

    map_view = read_map(bot, lattice_spacing=4)

    assert map_view.production_sites == (FREE, FARTHER)


def test_keep_clear_takes_the_corridor_out_of_ares_placement() -> None:
    bot = FakeBot()
    bot.mediator.get_placements_dict = placements(*SITES)

    cleared = structure_behavior.keep_clear(bot, StructureControl().corridor(SITE_MAP))

    main = bot.mediator.get_placements_dict[MAP.own_start][BuildingSize.THREE_BY_THREE]
    assert cleared == 1
    assert [site for site, info in main.items() if not info["available"]] == [IN_THE_CORRIDOR]


def test_the_log_says_which_sites_are_kept_clear() -> None:
    logger = FakeLogger()

    Logs(logger).kept_clear(0.0, SITE_MAP, (IN_THE_CORRIDOR,), 1)

    (event,) = logger.named("planner.production_kept_clear")
    assert event["data"] == {"production_sites": 5, "sites": [[14.5, 14.5]], "cleared": 1}

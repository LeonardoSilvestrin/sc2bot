from __future__ import annotations

from dataclasses import replace

import numpy as np
from ares.behaviors.combat.individual import PathUnitToTarget
from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import BaseView
from bot.awareness import AwarenessModel
from bot.body import behaviors
from bot.body.behaviors import intel as intel_behavior
from bot.body.behaviors import sensor_towers as sensor_tower_behavior
from bot.body.engine import Engine
from bot.ego.planners import Command, EconomyPlan, Proposal, StructurePlan, intel
from bot.ego.planners.intel import IntelPlanner, scouting_route
from bot.ego.planners.intel.sensor_towers import (
    MIN_BASES,
    SITE_COVER_RADIUS,
)

from .fakes import (
    LATTICE,
    MAP,
    SIZE,
    TOPOLOGY,
    FakeBot,
    FakeUnit,
    attention,
    seen_everywhere,
    unit,
)

ENEMY_MAIN = tuple(
    index
    for index, point in enumerate(LATTICE)
    if point.distance_to(MAP.enemy_start) <= 10.0
)
MAIN_MAP = replace(
    MAP,
    topology=replace(
        TOPOLOGY,
        regions=tuple(
            replace(region, sample_indices=ENEMY_MAIN)
            if region.region_id == TOPOLOGY.enemy_start_region
            else region
            for region in TOPOLOGY.regions
        ),
    ),
)
SCOUTING = UnitRole.SCOUTING.name
GATHERING = UnitRole.GATHERING.name


def scv(tag: int, x: float = 12.0, y: float = 8.0, *, role: str | None = GATHERING):
    return unit(tag, UnitTypeId.SCV, x, y, worker=True, role=role)


def frame(time: float, *, own_units=(), visible=(), workers=16, visibility=None):
    if visibility is None:
        visibility = np.zeros((SIZE, SIZE), dtype=np.uint8)
        for point in visible:
            visibility[int(point.y), int(point.x)] = 2
    return attention(
        time=time,
        own_units=own_units,
        workers=workers,
        visibility=visibility,
        map_view=MAIN_MAP,
    )


def intel_step(planner: IntelPlanner, state):
    return planner.plan(state, AwarenessModel().infer(state))


def test_no_scout_before_the_mineral_line_grows() -> None:
    state = frame(30.0, workers=intel.SCOUT_AT_WORKERS - 1)
    assert intel_step(IntelPlanner(), state).proposals == ()


def test_the_scout_asks_for_one_scv_and_goes_to_the_enemy_start_first() -> None:
    (proposal,) = intel_step(IntelPlanner(), frame(50.0)).proposals

    assert proposal.owner == intel.OWNER
    assert proposal.command is Command.SCOUT
    assert proposal.count == 1
    assert proposal.unit_types == frozenset({UnitTypeId.SCV})
    assert proposal.target == MAP.enemy_start
    assert proposal.priority == 1.0


def test_the_route_laps_the_edge_of_the_enemy_main() -> None:
    route = scouting_route(MAIN_MAP)

    assert route[0] == MAP.enemy_start
    lap = route[1:]
    assert 2 < len(lap) <= intel.LAP_SECTORS
    assert len(set(lap)) == len(lap)
    assert set(lap) <= {LATTICE[index] for index in ENEMY_MAIN}
    assert scouting_route(
        replace(MAP, topology=replace(TOPOLOGY, enemy_start_region=None))
    ) == (MAP.enemy_start,)


def test_the_scout_follows_the_route_as_it_comes_into_vision_then_goes_home() -> None:
    model = IntelPlanner()
    route = scouting_route(MAIN_MAP)
    scout = scv(100, 50, 50, role=SCOUTING)

    intel_step(model, frame(50.0))
    (proposal,) = intel_step(
        model, frame(60.0, own_units=(scout,), visible=route[:2])
    ).proposals
    assert proposal.target == route[2]
    assert proposal.reason == "lap_enemy_main"
    assert proposal.priority == (len(route) - 2) / len(route)

    assert not intel_step(
        model, frame(70.0, own_units=(scout,), visibility=seen_everywhere())
    ).proposals
    assert model.finished == "route_seen"


def test_a_lost_scout_is_not_replaced() -> None:
    model = IntelPlanner()
    intel_step(model, frame(50.0))
    intel_step(model, frame(51.0, own_units=(scv(100, role=SCOUTING),)))

    assert not intel_step(model, frame(60.0, own_units=(scv(101),))).proposals
    assert model.finished == "scout_lost"
    assert not intel_step(model, frame(61.0, own_units=(scv(101),))).proposals


def test_a_scout_that_cannot_finish_the_lap_goes_home() -> None:
    model = IntelPlanner()
    scout = scv(100, role=SCOUTING)
    intel_step(model, frame(50.0, own_units=(scout,)))

    assert not intel_step(
        model, frame(50.0 + intel.LAP_TIMEOUT, own_units=(scout,))
    ).proposals
    assert model.finished == "lap_timed_out"


def test_no_scout_once_the_early_game_is_over() -> None:
    model = IntelPlanner()

    assert intel_step(model, frame(intel.START_BY)).proposals == ()
    assert model.finished == "too_late"


def scout_proposal(target: Point2 = MAP.enemy_start) -> Proposal:
    return Proposal(
        proposal_id=intel.OWNER,
        owner=intel.OWNER,
        priority=1.0,
        command=Command.SCOUT,
        target=target,
        reason="test",
        count=1,
        unit_types=intel.SCOUT_TYPES,
    )


def army_proposal() -> Proposal:
    return Proposal(
        proposal_id="core_army",
        owner="core_army",
        priority=0.0,
        command=Command.HOLD,
        target=Point2((20.0, 20.0)),
        reason="test",
    )


def test_the_scout_comes_out_of_mining_and_stays_the_same_worker() -> None:
    engine = Engine()
    marine = unit(1, x=20, y=20)
    units = (
        marine,
        scv(100, 40, 40, role="BUILDING"),
        scv(101, 12, 8),
        scv(102, 16, 12),
    )

    first = engine.allocate(
        frame(50.0, own_units=units), (scout_proposal(), army_proposal())
    )

    assert dict(first.owners) == {1: "core_army", 102: intel.OWNER}
    assert first.unassigned == ()

    moved = (
        marine,
        scv(100, 40, 40, role="BUILDING"),
        scv(101, 20, 20),
        scv(102, 12, 8, role=SCOUTING),
    )
    second = engine.allocate(
        frame(51.0, own_units=moved), (scout_proposal(), army_proposal())
    )

    assert dict(second.owners)[102] == intel.OWNER


def test_the_scout_leaves_mining_and_goes_back_when_no_one_holds_it() -> None:
    bot = FakeBot()
    bot.units = [FakeUnit(100, UnitTypeId.SCV, 12, 8, dps=5.0)]
    economy = EconomyPlan(False, 22, 1, 1, False, False, (), "test")
    structures = StructurePlan(lower=(), reason="test")
    engine = Engine()
    miner = frame(50.0, own_units=(scv(100),))

    granted = engine.allocate(miner, (scout_proposal(),))
    behaviors.execute(bot, miner, granted, economy, structures)

    assert bot.mediator.role_of(100) == SCOUTING
    assert bot.mediator.removed_from_minerals == [100]
    (walk,) = [item for item in bot.registered if isinstance(item, PathUnitToTarget)]
    assert walk.unit.tag == 100 and walk.target == MAP.enemy_start

    scouting = frame(51.0, own_units=(scv(100, role=SCOUTING),))
    behaviors.execute(bot, scouting, engine.allocate(scouting, ()), economy, structures)

    assert bot.mediator.role_of(100) == GATHERING


def four_bases() -> tuple[BaseView, ...]:
    return (
        BaseView("main", Point2((10.5, 10.5)), True),
        BaseView("natural", Point2((22.5, 12.5)), False),
        BaseView("third", Point2((34.5, 20.5)), False),
        BaseView("outer", Point2((48.5, 36.5)), False),
    )


def test_sensor_coverage_activates_at_four_bases_and_selects_main_and_outermost() -> (
    None
):
    planner = IntelPlanner()

    before = intel_step(
        planner, attention(time=300.0, bases=four_bases()[: MIN_BASES - 1])
    )
    assert not planner.sensor_coverage_enabled
    assert before.sensor_towers.sites == ()

    plan = intel_step(planner, attention(time=301.0, bases=four_bases())).sensor_towers

    assert planner.sensor_coverage_enabled
    assert [site.base_id for site in plan.sites] == ["main", "outer"]
    assert plan.engineering_bay
    assert plan.sites[0].target.distance_to(MAP.enemy_start) < plan.sites[
        0
    ].base.distance_to(MAP.enemy_start)
    assert planner.views() == ()


def test_sensor_coverage_maintains_missing_sites_without_using_awareness() -> None:
    planner = IntelPlanner()
    ebay = unit(
        20,
        UnitTypeId.ENGINEERINGBAY,
        structure=True,
        power=0.0,
        ready=False,
    )
    initial = intel_step(
        planner, attention(time=300.0, bases=four_bases(), own_structures=(ebay,))
    ).sensor_towers
    main_site, outer_site = initial.sites
    main_tower = unit(
        21,
        UnitTypeId.SENSORTOWER,
        main_site.target.x + SITE_COVER_RADIUS,
        main_site.target.y,
        structure=True,
        power=0.0,
        ready=False,
    )

    result = intel_step(
        planner,
        attention(
            time=301.0,
            bases=four_bases(),
            own_structures=(ebay, main_tower),
        ),
    )

    plan = result.sensor_towers
    assert plan.sites == (outer_site,)
    assert not plan.engineering_bay
    assert plan.reason == "sensor_tower_needed"


def test_sensor_tower_behavior_builds_prerequisite_then_the_first_site() -> None:
    planner = IntelPlanner()
    first_plan = intel_step(planner, attention(time=300.0, bases=four_bases()))
    bot = FakeBot()

    building = intel_behavior.execute(bot, first_plan)
    report = sensor_tower_behavior.execute(bot, first_plan.sensor_towers)
    (ebay,) = bot.registered
    assert ebay.structure_id is UnitTypeId.ENGINEERINGBAY
    assert building == ("ENGINEERINGBAY",)
    assert report.building == ()

    existing_ebay = unit(20, UnitTypeId.ENGINEERINGBAY, structure=True, power=0.0)
    second_plan = intel_step(
        planner,
        attention(time=301.0, bases=four_bases(), own_structures=(existing_ebay,)),
    )
    bot.registered = []
    report = sensor_tower_behavior.execute(bot, second_plan.sensor_towers)

    (tower,) = bot.registered
    first = second_plan.sensor_towers.sites[0]
    assert tower.structure_id is UnitTypeId.SENSORTOWER
    assert tower.closest_to == first.target
    assert tower.sensor_tower and not tower.production and not tower.find_alternative
    assert report.building == ("SENSORTOWER",)


def test_sensor_coverage_rebuilds_without_a_mission_even_after_losing_bases() -> None:
    planner = IntelPlanner()
    ebay = unit(20, UnitTypeId.ENGINEERINGBAY, structure=True, power=0.0)
    state = attention(time=300.0, bases=four_bases(), own_structures=(ebay,))
    initial = intel_step(planner, state).sensor_towers
    towers = tuple(
        unit(
            30 + i,
            UnitTypeId.SENSORTOWER,
            site.target.x,
            site.target.y,
            structure=True,
            power=0.0,
        )
        for i, site in enumerate(initial.sites)
    )
    covered = intel_step(
        planner, replace(state, time=301.0, own_structures=(ebay, *towers))
    )
    assert covered.sensor_towers.sites == ()
    assert covered.sensor_towers.reason == "sensor_network_covered"
    rebuilt = intel_step(planner, replace(state, time=302.0))
    assert rebuilt.sensor_towers.sites == initial.sites
    fewer = intel_step(planner, replace(state, time=303.0, bases=four_bases()[:1]))
    assert [site.base_id for site in fewer.sensor_towers.sites] == ["main"]
    assert planner.views() == ()


def test_intel_consolidates_shared_engineering_bay_before_execution() -> None:
    from ares.behaviors.macro import BuildStructure

    planner = IntelPlanner()
    state = attention(time=300.0, bases=four_bases())
    awareness = replace(AwarenessModel().infer(state), cloak_seen_at=299.0)
    plan = planner.plan(state, awareness)
    assert plan.detection.engineering_bay and plan.sensor_towers.engineering_bay
    assert plan.engineering_bay
    bot = FakeBot()
    report = behaviors.execute(
        bot,
        state,
        Engine().allocate(state, ()),
        EconomyPlan(False, 22, 1, 1, False, False, (), "test"),
        StructurePlan((), "test"),
        plan,
    )
    builds = [item for item in bot.registered if isinstance(item, BuildStructure)]
    assert [item.structure_id for item in builds] == [UnitTypeId.ENGINEERINGBAY]
    assert report.infrastructure == ("ENGINEERINGBAY",)
    assert report.detection.building == report.sensor_towers.building == ()
    pending = unit(
        20, UnitTypeId.ENGINEERINGBAY, structure=True, power=0.0, ready=False
    )
    after = planner.plan(
        replace(state, time=301.0, own_structures=(pending,)), awareness
    )
    assert not after.engineering_bay
    # Destruction restores the desired prerequisite without opening an operation.
    assert planner.plan(replace(state, time=302.0), awareness).engineering_bay
    assert planner.views() == ()

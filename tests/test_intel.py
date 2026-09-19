from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from ares.behaviors.combat.individual import PathUnitToTarget
from ares.consts import BuildingSize, UnitRole
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from scipy.ndimage import label

from bot.attention import BaseView
from bot.attention.map import read_map
from bot.awareness import AwarenessModel
from bot.body import behaviors
from bot.body.behaviors import intel as intel_behavior
from bot.body.behaviors import sensor_towers as sensor_tower_behavior
from bot.body.engine import Engine
from bot.ego.planners import Command, EconomyPlan, Proposal, StructurePlan, intel
from bot.ego.planners.intel import DetectionConfig, IntelPlanner, scouting_route
from bot.ego.planners.intel.policies.sensor_towers import MIN_BASES, RADAR_RADIUS
from bot.ego.strategy import StrategicPosture, StrategyModel

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


def intent_for(state, awareness, posture: StrategicPosture | None = None):
    intent = StrategyModel().decide(state, awareness)
    return intent if posture is None else replace(intent, posture=posture)


def intel_step(planner: IntelPlanner, state, posture: StrategicPosture | None = None):
    awareness = AwarenessModel().infer(state)
    return planner.plan(state, awareness, intent_for(state, awareness, posture))


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


# A corner main whose other bases stand clear of the map's edges: only a tower
# in the main closes the air lane along the top edge.
MAIN_BASE = BaseView("main", Point2((20.5, 139.5)), True)
NATURAL_BASE = BaseView("natural", Point2((50.5, 119.5)), False)
THIRD_BASE = BaseView("third", Point2((28.5, 94.5)), False)
FOURTH_BASE = BaseView("fourth", Point2((62.5, 92.5)), False)
SENSOR_BASES = (MAIN_BASE, NATURAL_BASE, THIRD_BASE, FOURTH_BASE)
RING = ((10, 0), (-10, 0), (0, 10), (0, -10), (7, 7), (7, -7), (-7, 7), (-7, -7))
SENSOR_MAP = replace(
    MAP,
    bounds=(0.0, 0.0, 160.0, 160.0),
    own_start=MAIN_BASE.position,
    enemy_start=Point2((139.5, 20.5)),
    tower_sites=tuple(
        (
            base.position,
            tuple(
                sorted(
                    (base.position.offset(Point2(step)) for step in RING),
                    key=lambda point: (point.x, point.y),
                )
            ),
        )
        for base in sorted(SENSOR_BASES, key=lambda base: tuple(base.position))
    ),
)


def four_bases() -> tuple[BaseView, ...]:
    return SENSOR_BASES


def sensor_state(**kwargs):
    return attention(**{"map_view": SENSOR_MAP, "bases": four_bases(), **kwargs})


def tower(tag: int, position: Point2, *, ready: bool = True):
    return unit(
        tag,
        UnitTypeId.SENSORTOWER,
        position.x,
        position.y,
        structure=True,
        power=0.0,
        ready=ready,
    )


def open_bases(bases, towers) -> list[str]:
    """Bases an air unit reaches from the enemy start without entering radar."""

    min_x, min_y, max_x, max_y = (int(value) for value in SENSOR_MAP.bounds)
    ys, xs = np.mgrid[min_y:max_y, min_x:max_x] + 0.5
    free = np.ones(xs.shape, dtype=bool)
    for position in towers:
        free &= (xs - position.x) ** 2 + (ys - position.y) ** 2 > RADAR_RADIUS**2
    regions, _ = label(free)
    enemy = SENSOR_MAP.enemy_start
    reached = regions[int(enemy.y) - min_y, int(enemy.x) - min_x]
    return [
        base.base_id
        for base in bases
        if reached
        and regions[int(base.position.y) - min_y, int(base.position.x) - min_x] == reached
    ]


def test_sensor_coverage_activates_at_four_bases_and_seals_every_base() -> None:
    planner = IntelPlanner()

    before = intel_step(
        planner, sensor_state(time=300.0, bases=four_bases()[: MIN_BASES - 1])
    )
    assert not planner.sensor_coverage_enabled
    assert before.sensor_towers.sites == ()

    plan = intel_step(planner, sensor_state(time=301.0)).sensor_towers

    assert planner.sensor_coverage_enabled
    assert plan.engineering_bay
    assert open_bases(four_bases(), ()) == [base.base_id for base in four_bases()]
    assert open_bases(four_bases(), [site.target for site in plan.sites]) == []
    spots = dict(SENSOR_MAP.tower_sites)
    for site in plan.sites:
        assert site.target in spots[site.base]
    assert planner.views() == ()


def test_sensor_barrier_puts_a_tower_in_the_main_when_only_it_reaches_the_edge() -> None:
    plan = intel_step(IntelPlanner(), sensor_state(time=300.0)).sensor_towers

    # The sites nearest our start come first.
    assert plan.sites[0].site_id == "main"
    assert plan.sites[0].base == MAIN_BASE.position


def test_sensor_barrier_has_no_tower_it_could_do_without() -> None:
    plan = intel_step(IntelPlanner(), sensor_state(time=300.0)).sensor_towers
    targets = [site.target for site in plan.sites]

    for index in range(len(targets)):
        rest = targets[:index] + targets[index + 1 :]
        assert open_bases(four_bases(), rest) != []


def test_sensor_coverage_builds_on_standing_towers_without_using_awareness() -> None:
    planner = IntelPlanner()
    ebay = unit(20, UnitTypeId.ENGINEERINGBAY, structure=True, power=0.0, ready=False)
    initial = intel_step(
        planner, sensor_state(time=300.0, own_structures=(ebay,))
    ).sensor_towers
    first, *rest = initial.sites
    unfinished = tower(21, first.target, ready=False)

    plan = intel_step(
        planner, sensor_state(time=301.0, own_structures=(ebay, unfinished))
    ).sensor_towers

    assert plan.sites == tuple(rest)
    assert not plan.engineering_bay
    assert plan.reason == "sensor_tower_needed"


def test_sensor_tower_behavior_builds_prerequisite_then_the_first_site() -> None:
    planner = IntelPlanner()
    first_plan = intel_step(planner, sensor_state(time=300.0))
    bot = FakeBot()

    building = intel_behavior.execute(bot, first_plan)
    report = sensor_tower_behavior.execute(bot, first_plan.sensor_towers)
    (ebay,) = bot.registered
    assert ebay.structure_id is UnitTypeId.ENGINEERINGBAY
    assert building == ("ENGINEERINGBAY",)
    assert report.building == ()

    existing_ebay = unit(20, UnitTypeId.ENGINEERINGBAY, structure=True, power=0.0)
    second_plan = intel_step(
        planner, sensor_state(time=301.0, own_structures=(existing_ebay,))
    )
    bot.registered = []
    report = sensor_tower_behavior.execute(bot, second_plan.sensor_towers)

    (built,) = bot.registered
    first = second_plan.sensor_towers.sites[0]
    assert built.structure_id is UnitTypeId.SENSORTOWER
    assert built.closest_to == first.target
    assert built.base_location == first.base
    assert built.sensor_tower and not built.production and not built.find_alternative
    assert report.building == ("SENSORTOWER",)


def test_sensor_coverage_rebuilds_without_a_mission_even_after_losing_bases() -> None:
    planner = IntelPlanner()
    ebay = unit(20, UnitTypeId.ENGINEERINGBAY, structure=True, power=0.0)
    state = sensor_state(time=300.0, own_structures=(ebay,))
    initial = intel_step(planner, state).sensor_towers
    towers = tuple(tower(30 + i, site.target) for i, site in enumerate(initial.sites))
    covered = intel_step(
        planner, replace(state, time=301.0, own_structures=(ebay, *towers))
    )
    assert covered.sensor_towers.sites == ()
    assert covered.sensor_towers.reason == "sensor_network_covered"
    rebuilt = intel_step(planner, replace(state, time=302.0))
    assert rebuilt.sensor_towers.sites == initial.sites
    main_only = intel_step(
        planner, replace(state, time=303.0, bases=four_bases()[:1])
    ).sensor_towers
    assert [site.base for site in main_only.sites] == [MAIN_BASE.position]
    no_bases = intel_step(planner, replace(state, time=304.0, bases=())).sensor_towers
    assert no_bases.sites == ()
    assert no_bases.reason == "no_bases"
    assert planner.views() == ()


def test_read_map_keeps_ares_tower_spots_per_expansion_without_the_wall() -> None:
    bot = FakeBot()
    wall = Point2((17.0, 17.0))
    spots = (Point2((14.0, 6.0)), Point2((6.0, 14.0)))
    bot.mediator.get_placements_dict = {
        MAP.own_start: {
            BuildingSize.TWO_BY_TWO: {
                site: {"available": True, "is_wall": site == wall}
                for site in (*spots, wall)
            }
        }
    }

    map_view = read_map(bot, lattice_spacing=4)

    assert map_view.tower_sites == ((MAP.own_start, (spots[1], spots[0])),)


def test_intel_consolidates_shared_engineering_bay_before_execution() -> None:
    from ares.behaviors.macro import BuildStructure

    planner = IntelPlanner()
    state = sensor_state(time=300.0)
    awareness = replace(AwarenessModel().infer(state), cloak_seen_at=299.0)
    plan = planner.plan(state, awareness, intent_for(state, awareness))
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
    later = replace(state, time=301.0, own_structures=(pending,))
    after = planner.plan(later, awareness, intent_for(later, awareness))
    assert not after.engineering_bay
    # Destruction restores the desired prerequisite without opening an operation.
    rebuilt = replace(state, time=302.0)
    assert planner.plan(rebuilt, awareness, intent_for(rebuilt, awareness)).engineering_bay
    assert planner.views() == ()


# How Intel reads the posture.


def test_no_scout_sets_out_while_home_is_defended() -> None:
    planner = IntelPlanner()

    assert intel_step(planner, frame(50.0), StrategicPosture.DEFEND).proposals == ()
    assert planner.mission is None
    (proposal,) = intel_step(planner, frame(51.0)).proposals
    assert proposal.mission_id == "intel:scout:1"


@pytest.mark.parametrize(
    "posture, focus, held",
    [
        (StrategicPosture.DEFEND, "threat", True),
        (StrategicPosture.PRESSURE, "offense", True),
        (StrategicPosture.COMMIT, "offense", True),
        (StrategicPosture.DEVELOP, "economy", False),
        (StrategicPosture.RECOVER, "economy", False),
    ],
)
def test_orbitals_hold_a_scan_while_a_fight_is_expected(
    posture: StrategicPosture, focus: str, held: bool
) -> None:
    # No cloak seen: only the posture makes the Orbitals keep a scan.
    plan = intel_step(IntelPlanner(), frame(300.0), posture)

    assert plan.focus == focus
    assert plan.detection.energy_reserve == (DetectionConfig().scan_reserve if held else 0.0)
    assert dict(plan.detection.inputs)["scan_held"] == float(held)

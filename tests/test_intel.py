from __future__ import annotations

from dataclasses import replace

import numpy as np
from ares.behaviors.combat.individual import PathUnitToTarget
from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.body import behaviors
from bot.body.engine import Engine
from bot.ego.planners import Command, EconomyPlan, Proposal, StructurePlan, intel
from bot.ego.planners.intel import IntelPlanner, scouting_route

from .fakes import LATTICE, MAP, SIZE, TOPOLOGY, FakeBot, FakeUnit, attention, seen_everywhere, unit

ENEMY_MAIN = tuple(
    index for index, point in enumerate(LATTICE) if point.distance_to(MAP.enemy_start) <= 10.0
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


def test_no_scout_before_the_mineral_line_grows() -> None:
    assert IntelPlanner().plan(frame(30.0, workers=intel.SCOUT_AT_WORKERS - 1)) == ()


def test_the_scout_asks_for_one_scv_and_goes_to_the_enemy_start_first() -> None:
    (proposal,) = IntelPlanner().plan(frame(50.0))

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
    assert scouting_route(replace(MAP, topology=replace(TOPOLOGY, enemy_start_region=None))) == (
        MAP.enemy_start,
    )


def test_the_scout_follows_the_route_as_it_comes_into_vision_then_goes_home() -> None:
    model = IntelPlanner()
    route = scouting_route(MAIN_MAP)
    scout = scv(100, 50, 50, role=SCOUTING)

    model.plan(frame(50.0))
    (proposal,) = model.plan(frame(60.0, own_units=(scout,), visible=route[:2]))
    assert proposal.target == route[2]
    assert proposal.reason == "lap_enemy_main"
    assert proposal.priority == (len(route) - 2) / len(route)

    assert model.plan(frame(70.0, own_units=(scout,), visibility=seen_everywhere())) == ()
    assert model.finished == "route_seen"


def test_a_lost_scout_is_not_replaced() -> None:
    model = IntelPlanner()
    model.plan(frame(50.0))
    model.plan(frame(51.0, own_units=(scv(100, role=SCOUTING),)))

    assert model.plan(frame(60.0, own_units=(scv(101),))) == ()
    assert model.finished == "scout_lost"
    assert model.plan(frame(61.0, own_units=(scv(101),))) == ()


def test_a_scout_that_cannot_finish_the_lap_goes_home() -> None:
    model = IntelPlanner()
    scout = scv(100, role=SCOUTING)
    model.plan(frame(50.0, own_units=(scout,)))

    assert model.plan(frame(50.0 + intel.LAP_TIMEOUT, own_units=(scout,))) == ()
    assert model.finished == "lap_timed_out"


def test_no_scout_once_the_early_game_is_over() -> None:
    model = IntelPlanner()

    assert model.plan(frame(intel.START_BY)) == ()
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

    first = engine.allocate(frame(50.0, own_units=units), (scout_proposal(), army_proposal()))

    assert dict(first.owners) == {1: "core_army", 102: intel.OWNER}
    assert first.unassigned == ()

    moved = (
        marine,
        scv(100, 40, 40, role="BUILDING"),
        scv(101, 20, 20),
        scv(102, 12, 8, role=SCOUTING),
    )
    second = engine.allocate(frame(51.0, own_units=moved), (scout_proposal(), army_proposal()))

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

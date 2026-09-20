"""Passages that blockers open and close, over a static identity."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import PassageWatch, pathable_lattice, read_blockers, read_map
from bot.attention.topology import (
    CLOSED,
    OPEN,
    UNKNOWN,
    MapBlocker,
    MapTopology,
    build_topology,
)
from bot.ego.planners.intel.planner import enemy_exits
from bot.ego.planners.map_control.policies.staging import Ground
from bot.logs import Logs
from bot.main import Layers, play_frame

from .fakes import FakeBot, FakeLogger, FakeUnit

SIZE = 64
# The corridor the wall stands in: the only ground between west and east.
GAP_Y = range(28, 36)
WALL_X = range(30, 34)
OWN_START = Point2((10.5, 10.5))
ENEMY_START = Point2((53.5, 53.5))
# East of the wall, so the enemy's natural and third are behind it.
EXPANSIONS = [
    OWN_START,
    Point2((20.5, 40.5)),
    Point2((44.5, 20.5)),
    Point2((44.5, 40.5)),
    ENEMY_START,
]
# The long way round, which only exists on the two-way map.
DETOUR_Y = range(4, 10)


def _grid(*, detour: bool = False) -> np.ndarray:
    """A map cut in two by a wall of cliff with one gap in it."""

    grid = np.zeros((SIZE, SIZE), dtype=np.uint8)
    grid[4:60, 4:60] = 1
    grid[:, 30:34] = 0
    for y in GAP_Y:
        grid[y, 30:34] = 1
    if detour:
        for y in DETOUR_Y:
            grid[y, 30:34] = 1
    return grid


def _map_data(*, detour: bool = False):
    """Two MapAnalyzer regions, west and east of the wall."""

    west = SimpleNamespace(label=0, center=Point2((16, 32)))
    east = SimpleNamespace(label=1, center=Point2((48, 32)))

    def in_region(point):
        x = float(point[0])
        if x < 30:
            return west
        if x >= 34:
            return east
        return None

    chokes = [
        SimpleNamespace(
            center=Point2((32, 32)),
            regions=(west, east),
            points=tuple((x, y) for x in WALL_X for y in GAP_Y),
            side_a=Point2((32, 28)),
            side_b=Point2((32, 35)),
            is_ramp=False,
            is_vision_blocker=False,
        )
    ]
    if detour:
        chokes.append(
            SimpleNamespace(
                center=Point2((32, 7)),
                regions=(west, east),
                points=tuple((x, y) for x in WALL_X for y in DETOUR_Y),
                side_a=Point2((32, 4)),
                side_b=Point2((32, 9)),
                is_ramp=False,
                is_vision_blocker=False,
            )
        )
    return SimpleNamespace(
        regions={region.label: region for region in (west, east)},
        in_region_p=in_region,
        map_chokes=tuple(chokes),
    )


def _mineral_wall(tags: range = range(100, 108)) -> tuple[MapBlocker, ...]:
    """A patch on every row of the gap: a line right across it, the way a map
    draws a mineral wall. Each patch covers the two cells beside it."""

    return tuple(
        MapBlocker(
            tag=tag,
            blocker_type="mineral_wall",
            position=Point2((float(WALL_X[3]), y + 0.5)),
            cells=((WALL_X[2], y), (WALL_X[3], y)),
        )
        for tag, y in zip(tags, GAP_Y, strict=True)
    )


def _rocks(tags: range = range(200, 202)) -> tuple[MapBlocker, ...]:
    """Two rocks, side by side across the gap."""

    return tuple(
        MapBlocker(
            tag=tag,
            blocker_type="destructible",
            position=Point2((32.0, GAP_Y[0] + 2.0 + 4 * index)),
            cells=tuple(
                (x, y)
                for x in WALL_X
                for y in range(GAP_Y[0] + 4 * index, GAP_Y[0] + 4 + 4 * index)
            ),
        )
        for index, tag in enumerate(tags)
    )


def _topology(
    blockers: tuple[MapBlocker, ...] = (), *, detour: bool = False
) -> MapTopology:
    grid = _grid(detour=detour)
    return build_topology(
        grid,
        pathable_lattice(grid, 4, (0.0, 0.0, float(SIZE), float(SIZE))),
        4.0,
        EXPANSIONS,
        OWN_START,
        ENEMY_START,
        map_data=_map_data(detour=detour),
        blockers=blockers,
    )


# --- the states a passage is in ---


def test_a_passage_nothing_stands_in_is_open() -> None:
    topology = _topology()

    (passage,) = topology.passages
    assert (passage.state, passage.is_open, passage.blocker_tags) == (OPEN, True, ())
    assert passage.blocker_type is None
    assert topology.open_passages() == topology.passages
    assert topology.blocked_passages() == ()


def test_a_mineral_wall_with_minerals_left_starts_closed() -> None:
    topology = _topology(_mineral_wall())

    (passage,) = topology.passages
    assert passage.state == CLOSED
    assert not passage.is_open and passage.is_closed
    assert passage.blocker_type == "mineral_wall"
    assert passage.blocker_tags == tuple(range(100, 108))
    assert topology.open_passages() == ()
    assert topology.blocked_passages() == topology.passages


def test_rocks_that_still_stand_start_closed() -> None:
    topology = _topology(_rocks())

    (passage,) = topology.passages
    assert (passage.state, passage.blocker_type) == (CLOSED, "destructible")
    assert passage.blocker_tags == (200, 201)


def test_touching_minerals_and_rocks_can_seal_a_passage_together() -> None:
    blockers = tuple(
        replace(blocker, blocker_type="destructible") if index % 2 else blocker
        for index, blocker in enumerate(_mineral_wall())
    )
    (passage,) = _topology(blockers).passages
    assert passage.state == CLOSED
    assert passage.blocker_type == "mixed"
    assert passage.blocker_tags == tuple(range(100, 108))


def test_a_blocker_beside_the_way_leaves_the_passage_open() -> None:
    """A rock in the open ground west of the gap closes nothing."""

    aside = MapBlocker(
        tag=300,
        blocker_type="destructible",
        position=Point2((20.0, 20.0)),
        cells=tuple((x, y) for x in range(18, 23) for y in range(18, 23)),
    )
    (passage,) = _topology((aside,)).passages

    assert passage.state == OPEN
    assert passage.blocker_tags == ()


# --- what the game changes, frame by frame ---


def _watch(topology: MapTopology, alive) -> MapTopology:
    from bot.attention.passages import passage_states

    return topology.with_passage_states(passage_states(topology, alive))


def test_losing_some_of_a_mineral_wall_keeps_it_closed() -> None:
    topology = _topology(_mineral_wall())
    left = frozenset(range(104, 108))

    updated = _watch(topology, left)

    assert updated is topology
    assert updated.passages[0].state == CLOSED


def test_losing_every_blocker_opens_the_passage() -> None:
    topology = _topology(_mineral_wall())

    updated = _watch(topology, frozenset())

    assert updated is not topology
    assert updated.passages[0].state == OPEN
    assert updated.passages[0].is_open
    # The identity of the passage did not move with its state.
    assert updated.passages[0].passage_id == topology.passages[0].passage_id
    assert updated.passages[0].blocker_tags == topology.passages[0].blocker_tags


def test_rocks_open_one_at_a_time_and_only_the_last_one_counts() -> None:
    topology = _topology(_rocks())

    half = _watch(topology, frozenset({201}))
    assert half.passages[0].state == CLOSED

    assert _watch(topology, frozenset()).passages[0].state == OPEN


def test_a_frame_that_cannot_look_says_unknown_rather_than_open() -> None:
    topology = _topology(_mineral_wall())

    updated = _watch(topology, None)

    assert updated.passages[0].state == UNKNOWN
    # Unknown is not a way through.
    assert not updated.passages[0].is_open
    assert updated.open_passages() == ()


# --- connectivity, and the identity underneath it ---


def test_connectivity_and_routes_change_when_the_wall_falls() -> None:
    topology = _topology(_mineral_wall())
    west, east = topology.own_start_region, topology.enemy_start_region
    assert west is not None and east is not None

    assert topology.connected_regions(west) == frozenset({west})
    assert topology.route(west, east) == ()
    assert not topology.reachable(west, east)
    # The static map still knows the way exists; only today's does not.
    assert topology.route(west, east, open_only=False) == (west, east)
    assert topology.connected_regions(west, open_only=False) == frozenset({west, east})

    opened = _watch(topology, frozenset())

    assert opened.connected_regions(west) == frozenset({west, east})
    assert opened.route(west, east) == (west, east)
    assert opened.reachable(west, east)


def test_the_detour_stays_the_route_while_the_short_way_is_walled() -> None:
    topology = _topology(_mineral_wall(), detour=True)
    west, east = topology.own_start_region, topology.enemy_start_region
    (walled,) = [p for p in topology.passages if p.is_closed]
    (free,) = [p for p in topology.passages if p.is_open]

    assert topology.reachable(west, east)
    assert {passage_id for _, passage_id in topology.neighbours(west, open_only=True)} == {
        free.passage_id
    }
    assert walled.passage_id in {
        passage_id for _, passage_id in topology.neighbours(west)
    }


def test_expansion_identity_holds_while_the_route_to_it_changes() -> None:
    bot = _bot(_wall_units())
    map_view = read_map(bot, lattice_spacing=4)
    natural, third = map_view.enemy_natural, map_view.enemy_third

    assert natural is not None and third is not None
    assert not map_view.reachable_now(third)
    assert map_view.route_to(third) == ()

    opened, changes = PassageWatch().refresh(_bot(()), map_view)

    # The same ground is still the enemy's natural and third...
    assert (opened.enemy_natural, opened.enemy_third) == (natural, third)
    assert opened.expansions == map_view.expansions
    assert opened.topology.expansion_to_region == map_view.topology.expansion_to_region
    # ... and only now can we walk to them.
    assert opened.reachable_now(third)
    assert opened.route_to(third) == (
        opened.topology.own_start_region,
        opened.topology.enemy_start_region,
    )
    assert [change.transition for change in changes] == ["CLOSED -> OPEN"]


# --- reading the blockers off the game ---


def _wall_units() -> list[FakeUnit]:
    return [
        FakeUnit(
            400 + index,
            UnitTypeId.RICHMINERALFIELD,
            float(blocker.position.x),
            float(blocker.position.y),
            structure=True,
            dps=0.0,
            minerals=5,
        )
        for index, blocker in enumerate(_mineral_wall())
    ]


def _bot(wall, *, base_minerals: bool = True) -> FakeBot:
    bot = FakeBot()
    bot.mediator.get_map_data_object = _map_data()
    bot.game_info.pathing_grid = SimpleNamespace(data_numpy=_grid())
    bot.expansion_locations_list = list(EXPANSIONS)
    bot.enemy_start_locations = [ENEMY_START]
    mined = FakeUnit(900, UnitTypeId.MINERALFIELD, 12.0, 10.0, structure=True, dps=0.0)
    bot.mineral_field = [*wall, mined] if base_minerals else list(wall)
    bot.expansion_locations_dict = {OWN_START: [mined]} if base_minerals else {}
    return bot


def test_read_blockers_tells_a_mineral_wall_from_a_base_s_minerals() -> None:
    blockers = read_blockers(_bot(_wall_units()))

    assert {blocker.tag for blocker in blockers} == {
        unit.tag for unit in _wall_units()
    }
    assert {blocker.blocker_type for blocker in blockers} == {"mineral_wall"}
    assert all(len(blocker.cells) == 2 for blocker in blockers)


def test_read_blockers_skips_scenery_destructibles() -> None:
    bot = _bot(())
    bot.destructables = [
        FakeUnit(500, UnitTypeId.UNBUILDABLEBRICKSDESTRUCTIBLE, 32.0, 31.0, dps=0.0),
        FakeUnit(501, UnitTypeId.INHIBITORZONESMALL, 32.0, 33.0, dps=0.0),
    ]
    for unit in bot.destructables:
        unit.radius = 2.0
        unit.name = unit.type_id.name

    assert read_blockers(bot) == ()


def test_read_map_starts_the_walled_passage_closed() -> None:
    map_view = read_map(_bot(_wall_units()), lattice_spacing=4)

    (passage,) = map_view.topology.passages
    assert passage.state == CLOSED
    assert passage.blocker_type == "mineral_wall"
    assert len(passage.blocker_tags) == len(_mineral_wall())


# --- the frame, and what it costs ---


def test_the_watch_keeps_the_same_map_until_a_passage_really_changes() -> None:
    bot = _bot(_wall_units())
    map_view = read_map(bot, lattice_spacing=4)
    watch = PassageWatch()

    first, changes = watch.refresh(bot, map_view)
    assert first is map_view and changes == ()

    # Half the wall mined out: still shut, still the same map.
    bot.mineral_field = bot.mineral_field[2:]
    second, changes = watch.refresh(bot, map_view)
    assert second is map_view and changes == ()

    bot.mineral_field = [unit for unit in bot.mineral_field if unit.tag == 900]
    third, changes = watch.refresh(bot, map_view)
    assert third is not map_view
    assert third.topology.passages[0].state == OPEN
    (change,) = changes
    assert (change.before, change.after) == (CLOSED, OPEN)
    assert (change.blocker_type, change.blockers_left) == ("mineral_wall", 0)

    # Nothing more to report once it is open.
    assert watch.refresh(bot, third) == (third, ())


def test_a_bot_that_will_not_list_its_neutrals_never_opens_a_passage() -> None:
    bot = _bot(_wall_units())
    map_view = read_map(bot, lattice_spacing=4)
    del bot.destructables

    updated, changes = PassageWatch().refresh(bot, map_view)

    assert updated.topology.passages[0].state == UNKNOWN
    assert [change.transition for change in changes] == ["CLOSED -> UNKNOWN"]


def test_watch_recovers_from_unknown_with_the_same_neutral_counts() -> None:
    bot = _bot(_wall_units())
    view = read_map(bot, lattice_spacing=4)
    watch = PassageWatch()
    watch.refresh(bot, view)
    del bot.destructables
    unknown, _ = watch.refresh(bot, view)
    bot.destructables = []
    restored, changes = watch.refresh(bot, unknown)
    assert restored.topology.passages[0].state == CLOSED
    assert [change.transition for change in changes] == ["UNKNOWN -> CLOSED"]


def test_watch_checks_tags_even_when_neutral_counts_do_not_change() -> None:
    bot = _bot(_wall_units())
    view = read_map(bot, lattice_spacing=4)
    watch = PassageWatch()
    watch.refresh(bot, view)
    for mineral in bot.mineral_field:
        mineral.tag += 1000
    opened, _ = watch.refresh(bot, view)
    assert opened.topology.passages[0].state == OPEN


def test_depleted_minerals_open_a_passage_without_a_count_change() -> None:
    bot = _bot(_wall_units())
    view = read_map(bot, lattice_spacing=4)
    watch = PassageWatch()
    watch.refresh(bot, view)
    for mineral in bot.mineral_field:
        mineral.mineral_contents = 0
    opened, _ = watch.refresh(bot, view)
    assert opened.topology.passages[0].state == OPEN


def test_snapshot_without_mineral_contents_is_still_a_blocker() -> None:
    bot = _bot(_wall_units())
    view = read_map(bot, lattice_spacing=4)
    for mineral in bot.mineral_field:
        mineral.mineral_contents = 0
        mineral.is_snapshot = True
    updated, changes = PassageWatch().refresh(bot, view)
    assert updated is view
    assert changes == ()


def test_scout_waits_for_a_wall_to_open_without_changing_expansion_identity() -> None:
    from bot.ego.missions import MissionFeedback
    from bot.ego.planners.intel.missions.early_scout import EarlyScoutMission

    from .fakes import attention

    walled = read_map(_bot(_wall_units()), lattice_spacing=4)
    mission = EarlyScoutMission(
        "intel:early_scout:1", (walled.enemy_start,), 0.0,
        natural=walled.enemy_natural, third=walled.enemy_third,
    )
    state = attention(map_view=walled)
    assert mission.step(state, frozenset(), MissionFeedback()) == ()
    assert mission.active
    opened, _ = PassageWatch().refresh(_bot(()), walled)
    (proposal,) = mission.step(replace(state, map=opened), frozenset(), MissionFeedback())
    assert proposal.target == walled.enemy_natural
    assert mission.third == walled.enemy_third


def test_intel_refreshes_active_scout_watchpoints_when_a_passage_opens() -> None:
    from bot.ego.planners.intel import IntelPlanner

    from .fakes import attention
    from .test_intel import intel_step

    walled = read_map(_bot(_wall_units()), lattice_spacing=4)
    planner = IntelPlanner()
    intel_step(planner, attention(map_view=walled, workers=16))
    mission = planner.mission
    assert mission is not None and planner.exits == ()
    opened, _ = PassageWatch().refresh(_bot(()), walled)
    intel_step(planner, attention(map_view=opened, workers=16))
    assert planner.mission is mission
    assert planner.exits == enemy_exits(opened)
    assert all(point in mission.ring for point in planner.exits)


def test_surveillance_waits_when_its_entire_ring_is_blocked() -> None:
    from bot.ego.missions import MissionFeedback
    from bot.ego.planners.intel.missions.early_scout import EarlyScoutMission, ScoutPhase

    from .fakes import attention

    walled = read_map(_bot(_wall_units()), lattice_spacing=4)
    mission = EarlyScoutMission(
        "intel:early_scout:1", (walled.enemy_start,), 0.0,
        natural=walled.enemy_natural, third=walled.enemy_third,
    )
    mission.phase = ScoutPhase.SURVEIL
    assert mission.step(attention(map_view=walled), frozenset(), MissionFeedback()) == ()
    assert mission.active
    opened, _ = PassageWatch().refresh(_bot(()), walled)
    assert mission.step(attention(map_view=opened), frozenset(), MissionFeedback())


def test_the_frame_reports_a_passage_opening_once() -> None:
    bot = _bot(_wall_units())
    bot.townhalls = [FakeUnit(1, UnitTypeId.COMMANDCENTER, 10.5, 10.5, structure=True)]
    logger = FakeLogger()
    layers = Layers(map_view=read_map(bot, lattice_spacing=4), logs=Logs(logger))

    play_frame(bot, 0, layers)
    assert logger.named("map.passage_changed") == []

    bot.mineral_field = [unit for unit in bot.mineral_field if unit.tag == 900]
    bot.time = 1.0
    play_frame(bot, 1, layers)
    bot.time = 2.0
    play_frame(bot, 2, layers)

    (event,) = logger.named("map.passage_changed")
    assert event["iteration"] == 1
    assert event["data"] == {
        "passage_id": "choke:0",
        "transition": "CLOSED -> OPEN",
        "from": "closed",
        "to": "open",
        "blocker_type": "mineral_wall",
        "blockers_left": 0,
        "regions": ["region:0", "region:1"],
        "position": [32.0, 32.0],
    }


# --- the routines that depend on connectivity ---


def test_staging_walks_no_walled_passage() -> None:
    walled = read_map(_bot(_wall_units()), lattice_spacing=4)
    ground = Ground(walled)

    assert ground.open == frozenset({walled.topology.enemy_start_region})

    opened, _ = PassageWatch().refresh(_bot(()), walled)
    ground = Ground(opened)

    assert ground.open == {
        region.region_id for region in opened.topology.regions
    }


def test_a_walled_exit_is_not_a_way_out_of_the_enemy_main() -> None:
    walled = read_map(_bot(_wall_units()), lattice_spacing=4)

    assert enemy_exits(walled) == ()

    opened, _ = PassageWatch().refresh(_bot(()), walled)

    assert enemy_exits(opened) == (opened.topology.passages[0].position,)


def test_proxy_search_excludes_an_expansion_behind_a_wall_until_it_opens() -> None:
    from bot.ego.planners.intel.policies.proxy import proxy_route

    bot = _bot(_wall_units())
    isolated = Point2((40.5, 12.5))
    bot.expansion_locations_list.append(isolated)
    walled = read_map(bot, lattice_spacing=4)
    assert isolated not in proxy_route(walled)
    bot.mineral_field = []
    opened, _ = PassageWatch().refresh(bot, walled)
    assert isolated in proxy_route(opened)


# --- what may not be built ---


def test_a_passage_may_not_be_shut_without_blockers() -> None:
    from dataclasses import replace

    topology = _topology()
    shut = replace(
        topology,
        passages=tuple(
            replace(passage, state=CLOSED) for passage in topology.passages
        ),
    )

    from bot.attention.topology import _validate

    with pytest.raises(ValueError, match="blockers"):
        _validate(shut, tuple(position for position, _ in shut.expansion_to_region))

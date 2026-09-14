from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from sc2.position import Point2

import bot.attention as attention_module
from bot.attention import pathable_lattice, read_map
from bot.logs import Logs
from bot.main import Layers, play_frame
from bot.map_topology import MapTopology, build_topology

from .fakes import FakeBot, FakeLogger


def _map_data(*, reverse: bool = False):
    left = SimpleNamespace(label=0, center=Point2((10, 32)))
    middle = SimpleNamespace(label=1, center=Point2((32, 32)))
    right = SimpleNamespace(label=2, center=Point2((54, 32)))
    ordered = [left, middle, right]
    if reverse:
        ordered.reverse()

    def in_region(point):
        x = float(point[0])
        if x < 20:
            return left
        if 24 <= x < 42:
            return middle
        if x >= 46:
            return right
        return None

    chokes = [
        SimpleNamespace(
            center=Point2((22, 32)),
            regions=(middle, left) if reverse else (left, middle),
            side_a=Point2((22, 30)),
            side_b=Point2((22, 34)),
            is_ramp=False,
            is_vision_blocker=False,
        ),
        SimpleNamespace(
            center=Point2((44, 32)),
            regions=(right, middle) if reverse else (middle, right),
            side_a=Point2((44, 29)),
            side_b=Point2((44, 35)),
            is_ramp=False,
            is_vision_blocker=False,
        ),
    ]
    if reverse:
        chokes.reverse()
    return SimpleNamespace(
        regions={region.label: region for region in ordered},
        in_region_p=in_region,
        map_chokes=tuple(chokes),
    )


def _known_topology(*, reverse: bool = False) -> MapTopology:
    grid = np.ones((64, 64), dtype=np.uint8)
    lattice = pathable_lattice(grid, 4, (0.0, 0.0, 64.0, 64.0))
    expansions = [
        Point2((10.5, 10.5)),
        Point2((12.5, 50.5)),
        Point2((30.5, 12.5)),
        Point2((53.5, 53.5)),
    ]
    if reverse:
        expansions.reverse()
    return build_topology(
        grid,
        lattice,
        4.0,
        expansions,
        Point2((10.5, 10.5)),
        Point2((53.5, 53.5)),
        map_data=_map_data(reverse=reverse),
    )


def test_known_map_builds_a_deterministic_base_aware_graph() -> None:
    topology = _known_topology()

    assert topology == _known_topology(reverse=True)
    assert [region.region_id for region in topology.regions] == [
        "region:0",
        "region:1",
        "region:2",
    ]
    assert [(passage.kind, passage.regions) for passage in topology.passages] == [
        ("choke", ("region:0", "region:1")),
        ("choke", ("region:1", "region:2")),
    ]
    assert topology.own_start_region == "region:0"
    assert topology.enemy_start_region == "region:2"

    expansion_regions = dict(topology.expansion_to_region)
    assert len(expansion_regions) == 4
    assert set(expansion_regions.values()) <= {
        region.region_id for region in topology.regions
    }
    # Two bases in one uninterrupted physical area remain two identified slots
    # associated with the same honest region; no imaginary choke is introduced.
    assert expansion_regions[Point2((10.5, 10.5))] == "region:0"
    assert expansion_regions[Point2((12.5, 50.5))] == "region:0"


def test_passages_and_adjacency_reference_valid_regions_symmetrically() -> None:
    topology = _known_topology()
    region_ids = {region.region_id for region in topology.regions}

    for passage in topology.passages:
        assert len(passage.regions) >= 2
        assert len(set(passage.regions)) == len(passage.regions)
        assert set(passage.regions) <= region_ids
    for region_id, links in topology.adjacency:
        for neighbour, passage_id in links:
            assert (region_id, passage_id) in topology.neighbours(neighbour)


def test_read_map_builds_once_and_frames_reuse_the_frozen_topology(monkeypatch) -> None:
    calls = 0
    real_builder = attention_module.build_topology

    def counted_builder(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(attention_module, "build_topology", counted_builder)
    bot = FakeBot()
    bot.mediator.get_map_data_object = _map_data()
    map_view = read_map(bot, lattice_spacing=4)
    topology = map_view.topology

    layers = Layers(map_view=map_view, logs=Logs())
    first = play_frame(bot, 0, layers)
    bot.time = 1.0
    second = play_frame(bot, 1, layers)

    assert calls == 1
    assert first.attention.map.topology is topology
    assert second.attention.map.topology is topology
    assert set(map_view.expansions) == {
        position for position, _ in topology.expansion_to_region
    }
    assert topology.own_start_region is not None
    assert topology.enemy_start_region is not None


def test_topology_is_logged_once_at_game_start() -> None:
    logger = FakeLogger()
    bot = FakeBot()
    bot.mediator.get_map_data_object = _map_data()
    map_view = read_map(bot, lattice_spacing=4)

    logs = Logs(logger)
    logs.game_started(bot, map_view, {})

    (event,) = logger.named("map.topology_built")
    assert event["iteration"] is None
    assert event["data"] == {
        "regions": 3,
        "passages": 2,
        "chokes": 2,
        "expansions": 3,
        "unresolved_expansions": 0,
        "own_start_region": "region:0",
        "enemy_start_region": "region:2",
    }

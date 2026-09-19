from __future__ import annotations

import ast
import inspect
from dataclasses import replace

import pytest
from sc2.position import Point2

from bot.attention import BaseView
from bot.attention.topology import MapPassage, MapRegion, MapTopology
from bot.body.engine import Engine
from bot.ego.planners import Command
from bot.ego.planners.military import map_control
from bot.ego.planners.military.map_control import (
    MAP_CONTROL_PRIORITY,
    MapControlConfig,
    MapControlPlanner,
    anchor,
)
from bot.ego.planners.military.map_control import planner as map_control_planner
from bot.ego.planners.military.offense import planner as offense_planner
from bot.ego.planners.military.offense.missions import main_attack
from bot.ego.strategy import Objective, StrategyModel
from bot.logs import Logs
from bot.main import Layers, play_frame

from .fakes import LATTICE, MAIN, MAP, NATURAL, FakeLogger, attention, proposal, unit
from .test_frame_flow import build_bot
from .test_strategy import awareness


def held(danger: float = 0.0, *, bases=(MAIN,), planner: MapControlPlanner | None = None):
    frame = attention(bases=bases)
    believed = awareness(danger, bases=bases)
    strategy = StrategyModel().decide(frame, believed)
    return strategy, (planner or MapControlPlanner()).plan(frame, believed, strategy)


# --- the legacy rally, moved out of Strategy ---
# The fake map's regions have no lattice points: no passage anchor resolves.


def test_the_main_alone_is_held_at_the_main_ramp() -> None:
    strategy, plan = held()

    assert strategy.objective is Objective.BUILD_ADVANTAGE
    assert (plan.source, plan.fallback) == ("legacy", "anchor_unresolved")
    assert plan.anchor == MAP.main_ramp
    assert plan.reason == "hold_rally_build_advantage"


def test_a_threatened_base_is_held_while_stabilizing() -> None:
    strategy, plan = held(0.7)

    assert strategy.objective is Objective.STABILIZE
    assert plan.anchor == MAIN.position
    assert plan.reason == "hold_rally_stabilize"


def test_a_forward_base_moves_the_anchor_toward_the_enemy() -> None:
    _, plan = held(bases=(MAIN, NATURAL))

    assert plan.anchor == NATURAL.position.towards(MAP.enemy_start, 6.0)


# --- the residual owner ---


def test_it_holds_every_free_army_unit_below_every_other_planner() -> None:
    _, plan = held()

    (proposal,) = plan.proposals
    assert (proposal.proposal_id, proposal.owner) == (map_control.OWNER, map_control.OWNER)
    assert proposal.priority == MAP_CONTROL_PRIORITY < 0.0
    assert proposal.command is Command.HOLD
    assert proposal.count is None and proposal.minimum_power is None
    assert proposal.target == plan.anchor


# --- the passage held, on a map with a real topology ---
#
#   pocket -(border)- main -ramp- nat
#                                  |
#                               natchoke
#                                  |
#          third -thirdchoke- mid -enemyramp- enemy
#
# The pocket is a dead end behind the main: closing it shuts nothing of ours
# off. Every other passage lies between the enemy start and some base.

CENTERS = {
    "main": Point2((10.5, 10.5)),
    "nat": Point2((30.5, 10.5)),
    "third": Point2((10.5, 34.5)),
    "mid": Point2((34.5, 34.5)),
    "pocket": Point2((2.5, 2.5)),
    "enemy": Point2((54.5, 54.5)),
}
SITES = {name: CENTERS[name] for name in ("main", "nat", "third", "enemy")}
PASSAGES = (
    MapPassage("ramp", Point2((20.5, 10.5)), 3.0, ("main", "nat"), "choke"),
    MapPassage("natchoke", Point2((32.5, 22.5)), 5.0, ("nat", "mid"), "choke"),
    MapPassage("thirdchoke", Point2((22.5, 34.5)), 6.0, ("third", "mid"), "choke"),
    MapPassage("enemyramp", Point2((44.5, 44.5)), 3.0, ("mid", "enemy"), "choke"),
    MapPassage("pocketlink", Point2((6.5, 6.5)), None, ("main", "pocket"), "border"),
)


def _topology(*, samples: bool = True) -> MapTopology:
    names = tuple(CENTERS)
    nearest = [
        min(names, key=lambda name: (point.distance_to(CENTERS[name]), name)) for point in LATTICE
    ]
    links: dict[str, list[tuple[str, str]]] = {name: [] for name in names}
    for passage in PASSAGES:
        a, b = passage.regions
        links[a].append((b, passage.passage_id))
        links[b].append((a, passage.passage_id))
    return MapTopology(
        regions=tuple(
            MapRegion(
                name,
                CENTERS[name],
                sample_indices=(
                    tuple(index for index, owner in enumerate(nearest) if owner == name)
                    if samples
                    else ()
                ),
                expansions=(SITES[name],) if name in SITES else (),
            )
            for name in names
        ),
        passages=PASSAGES,
        adjacency=tuple((name, tuple(links[name])) for name in names),
        expansion_to_region=tuple(
            (SITES[name], name) for name in sorted(SITES, key=lambda n: (SITES[n].x, SITES[n].y))
        ),
        own_start_region="main",
        enemy_start_region="enemy",
    )


GRAPH_MAP = replace(
    MAP,
    own_start=SITES["main"],
    enemy_start=SITES["enemy"],
    main_ramp=Point2((20.0, 10.0)),
    expansions=tuple(sorted(SITES.values(), key=lambda point: (point.x, point.y))),
    topology=_topology(),
)
BASE = {
    name: BaseView(f"base:{name}", SITES[name], is_main=name == "main")
    for name in ("main", "nat", "third")
}


def planned(
    *names: str,
    planner: MapControlPlanner | None = None,
    map_view=GRAPH_MAP,
    danger: float = 0.0,
):
    bases = tuple(BASE[name] for name in names)
    frame = attention(bases=bases, map_view=map_view)
    believed = awareness(danger, bases=bases)
    strategy = StrategyModel().decide(frame, believed)
    return (planner or MapControlPlanner()).plan(frame, believed, strategy)


def scores(plan) -> dict[str, float]:
    return {candidate.passage_id: candidate.score for candidate in plan.candidates}


def test_the_main_alone_holds_its_ramp_from_the_main_side() -> None:
    plan = planned("main")

    assert (plan.source, plan.passage.passage_id, plan.fallback) == ("passage", "ramp", None)
    assert plan.passage.region_id == "main"
    assert plan.reason == "hold_passage_build_advantage"
    # Behind the ramp, on a lattice point of the main: not on the ramp itself.
    ramp = PASSAGES[0].position
    main = GRAPH_MAP.topology.region("main")
    assert plan.anchor in [GRAPH_MAP.lattice[index] for index in main.sample_indices]
    assert plan.anchor.distance_to(CENTERS["main"]) < ramp.distance_to(CENTERS["main"])
    assert plan.proposals[0].target == plan.anchor


def test_a_passage_that_shuts_off_more_bases_is_worth_more() -> None:
    plan = planned("main", "nat")
    natchoke, ramp = (
        next(item for item in plan.candidates if item.passage_id == name)
        for name in ("natchoke", "ramp")
    )

    assert (natchoke.protected_bases, ramp.protected_bases) == (
        ("base:main", "base:nat"),
        ("base:main",),
    )
    assert natchoke.protected > ramp.protected
    assert plan.passage.passage_id == "natchoke"
    assert plan.passage.region_id == "nat"


def test_a_dead_end_behind_our_bases_is_no_candidate() -> None:
    assert "pocketlink" not in scores(planned("main", "nat", "third"))


def test_the_enemy_ramp_shuts_off_every_base_but_does_not_win_from_afar() -> None:
    plan = planned("main", "nat", "third")
    enemy_ramp = next(item for item in plan.candidates if item.passage_id == "enemyramp")

    assert enemy_ramp.protected == 3.0 > plan.passage.protected
    assert plan.passage.passage_id == "natchoke"
    assert enemy_ramp.overextension > plan.passage.overextension


def test_the_same_frames_choose_the_same_anchor() -> None:
    def run():
        planner = MapControlPlanner()
        return [
            planned(*names, planner=planner)
            for names in (("main",), ("main", "nat"), ("main", "nat", "third"), ("main",))
        ]

    assert run() == run()


def test_a_challenger_inside_the_switch_margin_does_not_move_the_army() -> None:
    first = planned("main")
    gap = scores(planned("main", "nat"))["natchoke"] - scores(first)["ramp"]
    assert gap > 0.0

    def second(margin: float):
        planner = MapControlPlanner(MapControlConfig(switch_margin=margin))
        planned("main", planner=planner)
        return planned("main", "nat", planner=planner).passage.passage_id

    assert second(gap + 0.01) == "ramp"
    assert second(max(0.0, gap - 0.01)) == "natchoke"


def test_a_threatened_base_outranks_the_passage_while_stabilizing() -> None:
    plan = planned("main", "nat", danger=0.7)

    assert (plan.source, plan.anchor, plan.passage, plan.fallback) == (
        "threatened_base",
        BASE["main"].position,
        None,
        None,
    )
    assert plan.reason == "hold_rally_stabilize"
    # The candidates are still scored, and logged.
    assert "natchoke" in scores(plan)


@pytest.mark.parametrize(
    "map_view, fallback",
    [
        (replace(GRAPH_MAP, topology=MapTopology()), "no_separating_passage"),
        (
            replace(GRAPH_MAP, topology=replace(GRAPH_MAP.topology, enemy_start_region=None)),
            "no_separating_passage",
        ),
        (replace(GRAPH_MAP, topology=_topology(samples=False)), "anchor_unresolved"),
    ],
    ids=["no_topology", "no_enemy_region", "no_lattice_point"],
)
def test_without_a_passage_to_hold_the_legacy_anchor_is_held(map_view, fallback) -> None:
    plan = planned("main", map_view=map_view)

    assert (plan.source, plan.anchor, plan.passage, plan.fallback) == (
        "legacy",
        map_view.main_ramp,
        None,
        fallback,
    )
    assert plan.reason == "hold_rally_build_advantage"
    (proposal,) = plan.proposals
    assert proposal.target == map_view.main_ramp


def test_a_base_off_the_topology_is_protected_by_no_passage() -> None:
    stray = BaseView("base:stray", Point2((60.5, 4.5)), is_main=False)
    frame = attention(bases=(stray,), map_view=GRAPH_MAP)
    believed = awareness(0.0, bases=(stray,))
    plan = MapControlPlanner().plan(frame, believed, StrategyModel().decide(frame, believed))

    assert (plan.source, plan.fallback, plan.candidates) == (
        "legacy",
        "no_separating_passage",
        (),
    )


def test_defense_and_offense_still_take_the_units_it_holds() -> None:
    army = tuple(unit(tag, x=12, y=12) for tag in (1, 2, 3, 4))
    frame = attention(bases=(BASE["main"],), map_view=GRAPH_MAP, own_units=army)
    believed = awareness(0.0, bases=(BASE["main"],))
    held = MapControlPlanner().plan(frame, believed, StrategyModel().decide(frame, believed))
    guard = proposal("defense", 0.5, owner="defense", count=1)
    attack = proposal("offense", 0.0, owner="offense")

    alone = Engine().allocate(frame, held.proposals)
    contested = Engine().allocate(frame, (*held.proposals, guard, attack))

    assert alone.owner_of(1) == map_control.OWNER
    owners = {tag: contested.owner_of(tag) for tag in (1, 2, 3, 4)}
    assert sorted(owners.values()) == ["defense", "offense", "offense", "offense"]


def _imported(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }


def test_no_planner_reaches_into_another() -> None:
    # MapControl hands its anchor to the offense through the frame, never by import.
    assert not any(
        name.startswith("bot.ego.planners.military.")
        for name in _imported(map_control_planner) | _imported(anchor)
    )
    assert not any(
        "map_control" in name for name in _imported(offense_planner) | _imported(main_attack)
    )


def test_the_frame_holds_the_army_at_the_anchor_and_logs_why() -> None:
    logger = FakeLogger()

    frame = play_frame(build_bot(attackers=0), 3, Layers(map_view=GRAPH_MAP, logs=Logs(logger)))

    assert frame.map_control.source == "passage"
    (hold,) = [grant for grant in frame.result.grants if grant.proposal.owner == map_control.OWNER]
    assert hold.tags and hold.proposal.target == frame.map_control.anchor
    (logged,) = logger.named("behavior.map_control_planned")
    data = logged["data"]
    assert (data["source"], data["passage"], data["region"], data["fallback"]) == (
        "passage",
        "ramp",
        "main",
        None,
    )
    assert data["anchor"] == [frame.map_control.anchor.x, frame.map_control.anchor.y]
    assert data["candidate_count"] == len(data["candidates"]) == 3
    best = data["candidates"][0]
    assert best["passage"] == "ramp"
    assert best["score"] == pytest.approx(
        best["protected"] + best["quality"] - best["overextension"]
    )

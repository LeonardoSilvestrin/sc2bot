from __future__ import annotations

import ast
import inspect
from dataclasses import replace

import numpy as np
import pytest
from sc2.position import Point2

from bot.attention import BaseView, MapView
from bot.attention.topology import MapPassage, MapRegion, MapTopology
from bot.awareness import InfluenceField
from bot.body.engine import Engine
from bot.ego.planners import Command
from bot.ego.planners.military import map_control
from bot.ego.planners.military.map_control import (
    MAP_CONTROL_PRIORITY,
    MapControlConfig,
    MapControlPlanner,
    anchor,
    staging,
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

PASSAGE_POLICY = MapControlConfig(policy="passage")


def held(danger: float = 0.0, *, bases=(MAIN,), planner: MapControlPlanner | None = None):
    frame = attention(bases=bases)
    believed = awareness(danger, bases=bases)
    strategy = StrategyModel().decide(frame, believed)
    return strategy, (planner or MapControlPlanner()).plan(frame, believed, strategy)


# --- the legacy rally, moved out of Strategy ---
# The fake map's regions have no lattice points: no policy places an anchor.


def test_the_main_alone_is_held_at_the_main_ramp() -> None:
    strategy, plan = held()

    assert strategy.objective is Objective.BUILD_ADVANTAGE
    assert (plan.source, plan.policy, plan.fallback) == ("legacy", "staging", "no_candidates")
    assert plan.anchor == MAP.main_ramp
    assert plan.reason == "hold_rally_build_advantage"
    assert plan.staging is None
    assert plan.passage.fallback == "anchor_unresolved"


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


# --- the single passage, now kept beside the staging point for comparison ---
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
    return (planner or MapControlPlanner(PASSAGE_POLICY)).plan(frame, believed, strategy)


def scores(plan) -> dict[str, float]:
    return {candidate.passage_id: candidate.score for candidate in plan.passage.candidates}


def test_the_main_alone_holds_its_ramp_from_the_main_side() -> None:
    plan = planned("main")

    assert (plan.source, plan.passage.held.passage_id, plan.fallback) == ("passage", "ramp", None)
    assert plan.passage.held.region_id == "main"
    assert (plan.held_passage, plan.region) == ("ramp", "main")
    assert plan.reason == "hold_passage_build_advantage"
    # Behind the ramp, on a lattice point of the main: not on the ramp itself.
    ramp = PASSAGES[0].position
    main = GRAPH_MAP.topology.region("main")
    assert plan.anchor == plan.passage.anchor
    assert plan.anchor in [GRAPH_MAP.lattice[index] for index in main.sample_indices]
    assert plan.anchor.distance_to(CENTERS["main"]) < ramp.distance_to(CENTERS["main"])
    assert plan.proposals[0].target == plan.anchor


def test_a_passage_that_shuts_off_more_bases_is_worth_more() -> None:
    plan = planned("main", "nat")
    natchoke, ramp = (
        next(item for item in plan.passage.candidates if item.passage_id == name)
        for name in ("natchoke", "ramp")
    )

    assert (natchoke.protected_bases, ramp.protected_bases) == (
        ("base:main", "base:nat"),
        ("base:main",),
    )
    assert natchoke.protected > ramp.protected
    assert plan.passage.held.passage_id == "natchoke"
    assert plan.passage.held.region_id == "nat"


def test_a_dead_end_behind_our_bases_is_no_candidate() -> None:
    assert "pocketlink" not in scores(planned("main", "nat", "third"))


def test_the_enemy_ramp_shuts_off_every_base_but_does_not_win_from_afar() -> None:
    plan = planned("main", "nat", "third")
    enemy_ramp = next(item for item in plan.passage.candidates if item.passage_id == "enemyramp")

    assert enemy_ramp.protected == 3.0 > plan.passage.held.protected
    assert plan.passage.held.passage_id == "natchoke"
    assert enemy_ramp.overextension > plan.passage.held.overextension


def test_the_same_frames_choose_the_same_anchor() -> None:
    def run(config):
        planner = MapControlPlanner(config)
        return [
            planned(*names, planner=planner)
            for names in (("main",), ("main", "nat"), ("main", "nat", "third"), ("main",))
        ]

    for config in (PASSAGE_POLICY, MapControlConfig()):
        assert run(config) == run(config)


def test_a_challenger_inside_the_switch_margin_does_not_move_the_army() -> None:
    first = planned("main")
    gap = scores(planned("main", "nat"))["natchoke"] - scores(first)["ramp"]
    assert gap > 0.0

    def second(margin: float):
        planner = MapControlPlanner(MapControlConfig(policy="passage", switch_margin=margin))
        planned("main", planner=planner)
        return planned("main", "nat", planner=planner).passage.held.passage_id

    assert second(gap + 0.01) == "ramp"
    assert second(max(0.0, gap - 0.01)) == "natchoke"


@pytest.mark.parametrize("config", [PASSAGE_POLICY, MapControlConfig()], ids=["passage", "staging"])
def test_a_threatened_base_outranks_the_policy_while_stabilizing(config) -> None:
    plan = planned("main", "nat", danger=0.7, planner=MapControlPlanner(config))

    assert (plan.source, plan.anchor, plan.fallback) == (
        "threatened_base",
        BASE["main"].position,
        None,
    )
    assert (plan.held_passage, plan.region) == (None, None)
    assert plan.reason == "hold_rally_stabilize"
    # Both policies are still evaluated, and logged.
    assert "natchoke" in scores(plan)
    assert plan.staging is not None and plan.staging.advance == 0.0


@pytest.mark.parametrize(
    "map_view, fallback, shadow",
    [
        (replace(GRAPH_MAP, topology=MapTopology()), "no_enemy_route", "no_separating_passage"),
        (
            replace(GRAPH_MAP, topology=replace(GRAPH_MAP.topology, enemy_start_region=None)),
            "no_enemy_route",
            "no_separating_passage",
        ),
        (
            replace(GRAPH_MAP, topology=_topology(samples=False)),
            "no_candidates",
            "anchor_unresolved",
        ),
    ],
    ids=["no_topology", "no_enemy_region", "no_lattice_point"],
)
def test_without_a_place_to_stage_the_legacy_anchor_is_held(map_view, fallback, shadow) -> None:
    for config, expected in ((MapControlConfig(), fallback), (PASSAGE_POLICY, shadow)):
        plan = planned("main", map_view=map_view, planner=MapControlPlanner(config))

        assert (plan.source, plan.anchor, plan.fallback) == ("legacy", map_view.main_ramp, expected)
        assert plan.reason == "hold_rally_build_advantage"
        (proposal,) = plan.proposals
        assert proposal.target == map_view.main_ramp


def test_a_base_off_the_topology_is_staged_from_the_region_nearest_it() -> None:
    stray = BaseView("base:stray", Point2((60.5, 4.5)), is_main=False)
    frame = attention(bases=(stray,), map_view=GRAPH_MAP)
    believed = awareness(0.0, bases=(stray,))
    strategy = StrategyModel().decide(frame, believed)

    shadow = MapControlPlanner(PASSAGE_POLICY).plan(frame, believed, strategy)
    staged = MapControlPlanner().plan(frame, believed, strategy)

    # No passage separates a base the topology does not know ...
    assert (shadow.source, shadow.fallback, shadow.passage.candidates) == (
        "legacy",
        "no_separating_passage",
        (),
    )
    # ... but the ground nearest it does.
    assert staged.source == "staging"
    assert staged.staging.bases == 1
    assert staged.staging.selected.worst_base == "base:stray"


# --- the staging point, on maps built region by region ---


def graph_map(
    centers: dict[str, tuple[float, float]],
    passages: tuple[tuple[str, tuple[float, float], float | None, tuple[str, str]], ...],
    sites: dict[str, tuple[float, float]],
    *,
    own: str = "main",
    enemy: str = "enemy",
    size: int = 128,
) -> MapView:
    """A map whose regions are the lattice points nearest each center."""

    lattice = tuple(
        Point2((x + 0.5, y + 0.5)) for y in range(2, size, 4) for x in range(2, size, 4)
    )
    names = tuple(sorted(centers))
    nearest = [
        min(names, key=lambda name: (point.distance_to(Point2(centers[name])), name))
        for point in lattice
    ]
    links: dict[str, list[tuple[str, str]]] = {name: [] for name in names}
    for passage_id, _, _, (first, second) in passages:
        links[first].append((second, passage_id))
        links[second].append((first, passage_id))
    expansions = sorted(
        ((Point2(site), name) for name, site in sites.items()),
        key=lambda item: (item[0].x, item[0].y),
    )
    return MapView(
        name="Graph",
        bounds=(0.0, 0.0, float(size), float(size)),
        own_start=Point2(sites[own]),
        enemy_start=Point2(sites[enemy]),
        main_ramp=Point2(sites[own]),
        expansions=tuple(point for point, _ in expansions),
        lattice=lattice,
        lattice_spacing=4.0,
        topology=MapTopology(
            regions=tuple(
                MapRegion(
                    name,
                    Point2(centers[name]),
                    sample_indices=tuple(
                        index for index, owner in enumerate(nearest) if owner == name
                    ),
                    expansions=(Point2(sites[name]),) if name in sites else (),
                )
                for name in names
            ),
            passages=tuple(
                MapPassage(
                    passage_id,
                    Point2(position),
                    width,
                    regions,
                    "choke" if width is not None else "border",
                )
                for passage_id, position, width, regions in passages
            ),
            adjacency=tuple((name, tuple(sorted(links[name]))) for name in names),
            expansion_to_region=tuple(expansions),
            own_start_region=own,
            enemy_start_region=enemy,
        ),
    )


# A map shaped like the ones the bot plays, drawn with the enemy top right:
#
#                                       enemy
#                                         | enemyramp
#          third -------thirdgate------- mid ---fifthlink--- fifth
#            | thirdlink                  | midlink
#            +--------------------------front ---fourthlink--- fourth
#                                         | natchoke (10 wide)
#                             main -ramp- nat
#
# The front is the open ground outside the natural. The third has an entrance
# of its own from the middle, so no passage guards every base once it is
# taken; the fifth lies on the far side of the middle, next to the enemy.
WIDE = graph_map(
    centers={
        "main": (14, 14),
        "nat": (40, 14),
        "front": (48, 40),
        "third": (18, 62),
        "fourth": (84, 18),
        "mid": (80, 76),
        "fifth": (116, 44),
        "enemy": (110, 112),
    },
    passages=(
        ("ramp", (26.5, 14.5), 4.0, ("main", "nat")),
        ("natchoke", (42.5, 26.5), 10.0, ("front", "nat")),
        ("thirdlink", (32.5, 52.5), 11.0, ("front", "third")),
        ("thirdgate", (24.5, 80.5), 11.0, ("mid", "third")),
        ("fourthlink", (66.5, 28.5), 11.0, ("front", "fourth")),
        ("midlink", (64.5, 58.5), 12.0, ("front", "mid")),
        ("fifthlink", (100.5, 60.5), 10.0, ("fifth", "mid")),
        ("enemyramp", (96.5, 94.5), 4.0, ("enemy", "mid")),
    ),
    sites={
        "main": (12.5, 12.5),
        "nat": (44.5, 8.5),
        "third": (10.5, 68.5),
        "fourth": (90.5, 10.5),
        "fifth": (120.5, 38.5),
        "enemy": (114.5, 116.5),
    },
)
TWO, THREE, FOUR, FIVE = (
    ("main", "nat"),
    ("main", "nat", "third"),
    ("main", "nat", "third", "fourth"),
    ("main", "nat", "third", "fourth", "fifth"),
)


def site(map_view: MapView, name: str) -> Point2:
    return next(point for point, region in map_view.topology.expansion_to_region if region == name)


def field(map_view: MapView, **readings) -> InfluenceField:
    """A field over the map's lattice; each reading an array or a constant."""

    count = len(map_view.lattice)
    threat, support, enemy = (
        np.broadcast_to(np.asarray(readings.get(name, 0.0), dtype=float), (count,)).copy()
        for name in ("threat", "support", "enemy")
    )
    return InfluenceField(map_view.lattice, map_view.lattice_spacing, threat, support, enemy)


def around(map_view: MapView, center: Point2, radius: float) -> np.ndarray:
    return np.array([point.distance_to(center) <= radius for point in map_view.lattice])


def staged(
    names,
    *,
    map_view: MapView = WIDE,
    influence: InfluenceField | None = None,
    objective: Objective | None = None,
    planner: MapControlPlanner | None = None,
    time: float = 0.0,
):
    bases = tuple(
        BaseView(f"base:{name}", site(map_view, name), is_main=name in ("main", "home"))
        for name in names
    )
    frame = attention(bases=bases, map_view=map_view, time=time)
    believed = replace(awareness(0.0, bases=bases), influence=influence or field(map_view))
    strategy = StrategyModel().decide(frame, believed)
    if objective is not None:
        strategy = replace(strategy, objective=objective)
    plan = (planner or MapControlPlanner()).plan(frame, believed, strategy)
    assert plan.source == "staging" and plan.staging is not None
    return plan


def test_case_a_the_natural_choke_still_holds_two_bases() -> None:
    main_only = staged(("main",)).staging.selected
    two = staged(TWO)

    assert main_only.passage_id == "ramp"
    point = two.staging.selected
    assert (point.region_id, point.passage_id) == ("nat", "natchoke")
    assert two.anchor == point.position
    assert (two.reason, two.held_passage, two.region) == (
        "hold_staging_build_advantage",
        "natchoke",
        "nat",
    )
    # The same passage the single-passage policy holds.
    assert two.passage.held.passage_id == "natchoke"


def test_case_b_a_third_outside_the_natural_moves_the_anchor_out_of_it() -> None:
    plan = staged(THREE)
    point = plan.staging.selected
    ground = staging.Ground(WIDE)
    bases = tuple(BaseView(f"base:{name}", site(WIDE, name), False) for name in THREE)
    candidates, _ = staging.evaluate(ground, bases, MapControlConfig())
    response = candidates.response(MapControlConfig().advance)
    natchoke = candidates.passages.index("natchoke")

    # Held from the natural choke, the third would be answered last and late.
    assert candidates.bases[int(response[natchoke].argmax())] == "base:third"
    assert point.worst < 0.5 * response[natchoke].max()
    # The anchor steps out between the natural and the third, not into it.
    assert point.region_id == "front"
    third, nat = site(WIDE, "third"), site(WIDE, "nat")
    assert point.position.distance_to(third) < candidates.position(natchoke).distance_to(third)
    assert point.position.distance_to(nat) < third.distance_to(nat)
    # The passage policy stays on the natural choke: logged beside, for comparison.
    assert plan.passage.held.passage_id == "natchoke"
    assert plan.passage.anchor != plan.anchor


# Two entrances that share no approach:
#
#        north_w --- enemy --- north_e
#           | P1                 | P2
#         west                 east
#            \westlink   eastlink/
#                     home
TWIN = graph_map(
    centers={
        "home": (62.5, 20),
        "west": (24.1, 44),
        "east": (100.9, 44),
        "north_w": (24.1, 88),
        "north_e": (100.9, 88),
        "enemy": (62.5, 118),
    },
    passages=(
        ("westlink", (38.5, 30.5), 10.0, ("home", "west")),
        ("eastlink", (86.5, 30.5), 10.0, ("east", "home")),
        ("P1", (24.1, 66.5), 6.0, ("north_w", "west")),
        ("P2", (100.9, 66.5), 6.0, ("east", "north_e")),
        ("nwlink", (43.3, 112.5), 12.0, ("enemy", "north_w")),
        ("nelink", (81.7, 112.5), 12.0, ("enemy", "north_e")),
    ),
    sites={
        "home": (62.5, 8.5),
        "west": (18.1, 50.5),
        "east": (106.9, 50.5),
        "enemy": (62.5, 122.5),
    },
    own="home",
)


def test_case_c_two_independent_entrances_are_answered_from_between_them() -> None:
    plan = staged(("home", "west", "east"), map_view=TWIN)
    point = plan.staging.selected
    ground = staging.Ground(TWIN)
    to_west, to_east = (
        ground.to(
            np.array([(point.position.x, point.position.y)]),
            point.region_id,
            site(TWIN, name),
            name,
            ground.table(site(TWIN, name), name),
        )[0]
        for name in ("west", "east")
    )

    # Neither entrance: the ground between them, answering both alike.
    assert point.passage_id not in ("P1", "P2")
    assert point.region_id == "home"
    assert abs(to_west - to_east) <= 2 * TWIN.lattice_spacing
    # No passage guards anything: each entrance can be walked around through the other.
    assert plan.passage.candidates == ()


# One entrance every approach crosses, the bases fanned out behind it.
FUNNEL = graph_map(
    centers={
        "hub": (64, 44),
        "main": (20, 20),
        "nat": (64, 12),
        "third": (108, 20),
        "outside": (64, 88),
        "enemy": (64, 118),
    },
    passages=(
        ("pa", (40.5, 30.5), 10.0, ("hub", "main")),
        ("pb", (64.5, 26.5), 10.0, ("hub", "nat")),
        ("pc", (88.5, 30.5), 10.0, ("hub", "third")),
        ("P1", (64.5, 66.5), 8.0, ("hub", "outside")),
        ("enemyramp", (64.5, 104.5), 4.0, ("enemy", "outside")),
    ),
    sites={
        "main": (14.5, 14.5),
        "nat": (64.5, 6.5),
        "third": (114.5, 14.5),
        "enemy": (64.5, 122.5),
    },
)


def test_case_d_one_entrance_to_every_base_is_still_the_place() -> None:
    plan = staged(("main", "nat", "third"), map_view=FUNNEL)
    point = plan.staging.selected

    assert (point.region_id, point.passage_id) == ("hub", "P1")
    assert point.choke > 0.0


def test_case_e_an_exposed_forward_point_gives_way_to_a_covered_one() -> None:
    calm = staged(FOUR).staging.selected
    hot = around(WIDE, calm.position, 14.0)
    pressed = staged(
        FOUR,
        influence=field(
            WIDE,
            threat=np.where(hot, 0.9, 0.0),
            support=np.where(hot, 0.05, 0.0),
            enemy=np.where(hot, 0.6, 0.0),
        ),
    ).staging.selected

    assert pressed.position != calm.position
    assert pressed.front < calm.front
    assert pressed.threat == 0.0 and pressed.exposure == 0.0
    # About as good at answering our bases: the field made the difference.
    assert abs(pressed.reaction - calm.reaction) < 0.02


def test_case_f_a_safe_expanded_territory_lets_the_anchor_advance() -> None:
    two = staged(TWO).staging.selected
    calm = staged(FOUR).staging.selected
    ours = staged(FOUR, influence=field(WIDE, support=0.9)).staging.selected

    # Support alone neither pulls the anchor nor holds it back.
    assert ours.position == calm.position
    assert ours.exposure == 0.0 and ours.support == pytest.approx(0.9)
    assert ours.front > 0.0
    enemy = WIDE.enemy_start
    assert ours.position.distance_to(enemy) < two.position.distance_to(enemy) - 20.0


def test_case_g_a_far_fifth_does_not_take_the_army_away_from_the_core() -> None:
    four = staged(FOUR).staging.selected
    plan = staged(FIVE).staging
    five = plan.selected
    fifth = site(WIDE, "fifth")
    core = [site(WIDE, name) for name in FOUR]
    center = Point2((sum(point.x for point in core) / 4, sum(point.y for point in core) / 4))

    # The fifth is the base answered last, and the anchor knows it ...
    assert five.worst_base == "base:fifth"
    # ... but it only leans toward it, and stays with the core.
    assert five.region_id == "front"
    assert five.position.distance_to(fifth) <= four.position.distance_to(fifth)
    assert five.position.distance_to(center) < five.position.distance_to(fifth)
    # Standing by the fifth would leave a base of the core answered later still.
    by_the_fifth = next(point for point in plan.top if point.region_id == "fifth")
    assert by_the_fifth.worst_base != "base:fifth"
    assert by_the_fifth.worst > five.worst


def test_the_anchor_moves_out_a_base_at_a_time() -> None:
    enemy = WIDE.enemy_start
    points = [staged(names).staging.selected for names in (("main",), TWO, THREE, FOUR, FIVE)]
    distances = [point.position.distance_to(enemy) for point in points]

    assert distances == sorted(distances, reverse=True)
    # No step jumps to the forward base: each is a short walk from the last.
    assert all(
        first.position.distance_to(second.position) < 32.0
        for first, second in zip(points, points[1:], strict=False)
    )


def test_stabilizing_only_covers() -> None:
    advancing = staged(THREE).staging
    stabilizing = staged(THREE, objective=Objective.STABILIZE).staging

    assert (advancing.advance, stabilizing.advance) == (MapControlConfig().advance, 0.0)
    assert stabilizing.selected.front < advancing.selected.front
    assert stabilizing.selected.mean <= advancing.selected.mean


def test_case_h_a_small_change_in_the_field_does_not_move_the_army() -> None:
    calm = staged(FOUR).staging.selected
    hot = around(WIDE, calm.position, 6.0)
    pressed = field(WIDE, threat=np.where(hot, 0.4, 0.0))

    def after(margin: float):
        planner = MapControlPlanner(MapControlConfig(staging_margin=margin))
        staged(FOUR, planner=planner)
        return staged(FOUR, planner=planner, influence=pressed, time=10.0)

    # The field alone makes some other point this much better than the held one.
    fresh = staged(FOUR, influence=pressed).staging.selected
    held = after(1.0).staging.selected
    assert held.position == calm.position
    gap = fresh.score - held.score
    assert gap > 0.0

    kept = after(gap + 0.01)
    assert (kept.anchor, kept.staging.switch, kept.staging.since) == (calm.position, "kept", 0.0)
    moved = after(max(0.0, gap - 0.01))
    assert moved.anchor == fresh.position
    assert (moved.staging.switch, moved.staging.since) == ("awareness", 10.0)
    assert moved.staging.previous == calm.position


def test_every_switch_says_why() -> None:
    planner = MapControlPlanner()

    first = staged(TWO, planner=planner).staging
    assert (first.switch, first.previous) == ("initial", None)
    assert staged(TWO, planner=planner).staging.switch == "kept"
    expanded = staged(THREE, planner=planner, time=5.0).staging
    assert (expanded.switch, expanded.previous) == ("bases_changed", first.selected.position)
    assert expanded.selected.region_id == "front"
    stabilizing = staged(THREE, planner=planner, objective=Objective.STABILIZE, time=6.0)
    assert stabilizing.staging.switch == "posture_changed"
    advancing = staged(THREE, planner=planner, time=7.0).staging
    assert (advancing.switch, advancing.selected) == ("posture_changed", expanded.selected)
    # Back to the main alone: the front is no ground of ours any more.
    lost = staged(("main",), planner=planner, time=8.0).staging
    assert lost.switch == "held_invalid"
    assert lost.selected.region_id == "main"


def test_the_top_candidates_are_the_best_of_their_regions() -> None:
    plan = staged(FOUR).staging

    assert plan.top[0] == plan.selected
    assert len(plan.top) == MapControlConfig().top_candidates
    assert len({point.region_id for point in plan.top}) == len(plan.top)
    assert [point.score for point in plan.top] == sorted(
        (point.score for point in plan.top), reverse=True
    )
    for point in plan.top:
        assert point.score == pytest.approx(-point.reaction + point.choke - point.exposure)


def test_no_candidate_stands_on_the_enemys_doorstep() -> None:
    ground = staging.Ground(WIDE)
    bases = tuple(BaseView(f"base:{name}", site(WIDE, name), False) for name in FIVE)
    candidates, fallback = staging.evaluate(ground, bases, MapControlConfig())

    assert fallback is None
    # The middle neighbours the fifth, and the enemy start.
    assert "mid" not in candidates.regions
    assert set(candidates.regions) == {"main", "nat", "front", "third", "fourth", "fifth"}


# --- the planners around it ---


def test_defense_and_offense_still_take_the_units_it_holds() -> None:
    army = tuple(unit(tag, x=12, y=12) for tag in (1, 2, 3, 4))
    frame = attention(bases=(BASE["main"],), map_view=GRAPH_MAP, own_units=army)
    believed = awareness(0.0, bases=(BASE["main"],))
    held = MapControlPlanner().plan(frame, believed, StrategyModel().decide(frame, believed))
    guard = proposal("defense", 0.5, owner="defense", count=1)
    attack = proposal("offense", 0.0, owner="offense")

    alone = Engine().allocate(frame, held.proposals)
    contested = Engine().allocate(frame, (*held.proposals, guard, attack))

    assert held.source == "staging"
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
        for name in _imported(map_control_planner) | _imported(anchor) | _imported(staging)
    )
    assert not any(
        "map_control" in name for name in _imported(offense_planner) | _imported(main_attack)
    )


def test_the_frame_holds_the_army_at_the_anchor_and_logs_why() -> None:
    logger = FakeLogger()

    frame = play_frame(build_bot(attackers=0), 3, Layers(map_view=GRAPH_MAP, logs=Logs(logger)))

    plan = frame.map_control
    assert plan.source == "staging"
    (hold,) = [grant for grant in frame.result.grants if grant.proposal.owner == map_control.OWNER]
    assert hold.tags and hold.proposal.target == plan.anchor
    (logged,) = logger.named("planner.map_control_planned")
    data = logged["data"]
    assert (data["source"], data["policy"], data["passage"], data["region"], data["fallback"]) == (
        "staging",
        "staging",
        "ramp",
        "main",
        None,
    )
    assert data["anchor"] == [plan.anchor.x, plan.anchor.y]
    logged_staging = data["staging"]
    assert (logged_staging["switch"], logged_staging["previous"]) == ("initial", None)
    assert logged_staging["objective"] == "BUILD_ADVANTAGE"
    assert logged_staging["candidate_count"] == plan.staging.candidate_count
    selected = logged_staging["selected"]
    assert selected == logged_staging["top"][0]
    assert selected["passage"] == "ramp"
    assert selected["worst_base"] == frame.attention.bases[0].base_id
    assert selected["score"] == pytest.approx(
        -selected["reaction"] + selected["choke"] - selected["exposure"], abs=1e-3
    )
    assert {"threat", "support", "control", "front", "mean", "worst"} <= set(selected)
    # The single-passage policy, logged beside it.
    shadow = data["shadow"]
    assert (shadow["policy"], shadow["passage"], shadow["fallback"]) == ("passage", "ramp", None)
    assert shadow["distance"] == pytest.approx(plan.anchor.distance_to(plan.passage.anchor))
    assert shadow["candidate_count"] == len(shadow["candidates"]) == 3
    best = shadow["candidates"][0]
    assert best["score"] == pytest.approx(
        best["protected"] + best["quality"] - best["overextension"]
    )

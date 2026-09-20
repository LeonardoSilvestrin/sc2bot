"""The early-game read of the enemy opening, across its three layers:

- ATTENTION (`bot.attention.opening`): the facts and their timestamps;
- AWARENESS (`bot.awareness.opening`): what those facts mean, by race;
- INTEL (`missions/early_scout.py`): the SCV that goes and gets them.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from ares.consts import UnitRole
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import (
    ExpansionObservation,
    ExpansionStatus,
    OpeningObservations,
    OpeningWatch,
    StructureObservation,
)
from bot.awareness import AwarenessModel, expectations_for, read_opening
from bot.awareness.opening import OpeningBeliefConfig
from bot.ego.missions import CancelMode, MissionStatus
from bot.ego.planners import Command
from bot.ego.planners.intel import (
    PROXY_CONFIDENCE_AT,
    PROXY_SEARCH_AT,
    SCOUT_AT_WORKERS,
    EarlyScoutMission,
    IntelPlanner,
    ScoutPhase,
    ScoutWindow,
    enemy_exits,
    proxy_route,
    scout_window,
    scouting_route,
)
from bot.ego.strategy import StrategyModel

from .fakes import LATTICE, MAP, SIZE, TOPOLOGY, attention, unit

ENEMY_MAIN = tuple(
    index for index, point in enumerate(LATTICE) if point.distance_to(MAP.enemy_start) <= 10.0
)
ENEMY_NATURAL = Point2((45.5, 33.5))
ENEMY_THIRD = Point2((33.5, 45.5))
# The enemy main is a region with samples (so the main can be covered) and the
# two expansions out of it come from Ares' own order.
OPENING_MAP = replace(
    MAP,
    expansions=(*MAP.expansions, ENEMY_NATURAL, ENEMY_THIRD),
    enemy_expansion_order=(ENEMY_NATURAL, ENEMY_THIRD),
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


def sight(*points: Point2) -> np.ndarray:
    grid = np.zeros((SIZE, SIZE), dtype=np.uint8)
    for point in points:
        grid[int(point.y), int(point.x)] = 2
    return grid


def structure(tag: int, type_id: UnitTypeId, position: Point2):
    return unit(tag, type_id, position.x, position.y, structure=True, power=0.0)


def frame(
    time: float,
    *,
    visible=(),
    enemy=(),
    enemy_units=(),
    own_units=(),
    workers=16,
    race=Race.Protoss,
):
    return attention(
        time=time,
        map_view=OPENING_MAP,
        visibility=sight(*visible),
        enemy_structures=enemy,
        enemy_units=enemy_units,
        own_units=own_units,
        workers=workers,
        enemy_race=race,
    )


# --- ATTENTION: the facts --------------------------------------------------


def test_nobody_looked_is_not_the_same_as_nothing_there() -> None:
    watch = OpeningWatch()

    unlooked = watch.observe(frame(60.0))
    assert unlooked.natural.status is ExpansionStatus.UNKNOWN
    assert (unlooked.natural_checked, unlooked.natural.last_checked_at) == (False, None)
    # Nothing was learned, so the record has no time either.
    assert unlooked.last_updated is None

    looked = watch.observe(frame(91.0, visible=(ENEMY_NATURAL,)))
    assert looked.natural.status is ExpansionStatus.ABSENT_CONFIRMED
    assert (looked.natural_checked, looked.natural.absent_at) == (True, 91.0)
    assert looked.last_updated == 91.0


def test_a_natural_confirmed_absent_and_then_found_gives_the_window_it_went_up_in() -> None:
    watch = OpeningWatch()
    watch.observe(frame(91.0, visible=(ENEMY_NATURAL,)))

    # Out of sight in between: the record keeps what it knew.
    kept = watch.observe(frame(120.0))
    assert kept.natural.status is ExpansionStatus.ABSENT_CONFIRMED

    hatchery = structure(7, UnitTypeId.NEXUS, ENEMY_NATURAL)
    found = watch.observe(frame(118.0, visible=(ENEMY_NATURAL,), enemy=(hatchery,)))

    assert found.natural.status is ExpansionStatus.PRESENT
    assert found.natural.first_seen_at == 118.0
    assert found.natural.appeared_between == (91.0, 118.0)

    # Seen once, it stays seen, and the first sighting is not overwritten.
    later = watch.observe(frame(150.0, visible=(ENEMY_NATURAL,), enemy=(hatchery,)))
    assert (later.natural.first_seen_at, later.natural.last_checked_at) == (118.0, 150.0)


def test_a_base_that_stood_there_is_never_confirmed_absent_afterwards() -> None:
    watch = OpeningWatch()
    nexus = structure(7, UnitTypeId.NEXUS, ENEMY_NATURAL)
    watch.observe(frame(118.0, visible=(ENEMY_NATURAL,), enemy=(nexus,)))

    razed = watch.observe(frame(200.0, visible=(ENEMY_NATURAL,)))

    assert razed.natural.status is ExpansionStatus.PRESENT
    assert razed.natural.last_checked_at == 200.0


def test_the_third_is_checked_apart_from_the_natural() -> None:
    watch = OpeningWatch()

    seen = watch.observe(
        frame(
            200.0,
            visible=(ENEMY_THIRD,),
            enemy=(structure(9, UnitTypeId.NEXUS, ENEMY_THIRD),),
        )
    )

    assert seen.third.status is ExpansionStatus.PRESENT
    assert (seen.third.first_seen_at, seen.third_checked) == (200.0, True)
    assert seen.natural.status is ExpansionStatus.UNKNOWN
    assert seen.natural_checked is False


def test_structures_are_counted_once_each_with_their_timestamps() -> None:
    watch = OpeningWatch()
    first = structure(1, UnitTypeId.GATEWAY, Point2((50.5, 50.5)))
    second = structure(2, UnitTypeId.GATEWAY, Point2((52.5, 50.5)))
    gas = structure(3, UnitTypeId.ASSIMILATOR, Point2((55.5, 55.5)))

    watch.observe(frame(100.0, enemy=(first, gas)))
    # The same Gateway again, plus a second one.
    seen = watch.observe(frame(107.0, enemy=(first, second, gas)))

    gateways = seen.structure(UnitTypeId.GATEWAY)
    assert (gateways.count_seen, gateways.first_seen_at, gateways.last_seen_at) == (2, 100.0, 107.0)
    assert seen.gases_seen == 1
    assert seen.structure(UnitTypeId.FORGE) == StructureObservation()
    assert seen.count((UnitTypeId.GATEWAY, UnitTypeId.WARPGATE)) == 2
    assert seen.first_seen((UnitTypeId.GATEWAY,)) == 100.0

    # A structure out of sight is not seen again, and nothing is lost.
    kept = watch.observe(frame(120.0))
    assert kept.structure(UnitTypeId.GATEWAY).count_seen == 2


def test_workers_units_and_proxy_structures_are_counted_where_they_stand() -> None:
    watch = OpeningWatch()
    probe = unit(20, UnitTypeId.PROBE, 55.0, 55.0, worker=True)
    zealot = unit(21, UnitTypeId.ZEALOT, 55.0, 55.0)
    overlord = unit(22, UnitTypeId.OVERLORD, 55.0, 55.0, power=0.0)
    at_home = structure(23, UnitTypeId.GATEWAY, Point2((14.5, 14.5)))

    seen = watch.observe(frame(120.0, enemy=(at_home,), enemy_units=(probe, zealot, overlord)))

    assert (seen.workers_seen, seen.early_combat_units_seen) == (1, 1)
    assert seen.proxy_structures_seen == 1


def test_the_main_coverage_tells_a_lap_from_a_glance() -> None:
    watch = OpeningWatch()
    main = [LATTICE[index] for index in ENEMY_MAIN]

    glance = watch.observe(frame(100.0, visible=main[:1]))
    lap = watch.observe(frame(120.0, visible=main))

    assert 0.0 < glance.main_scout_coverage < 0.5
    assert lap.main_scout_coverage == 1.0
    # Coverage is everything ever seen, not what is in sight now.
    assert watch.observe(frame(130.0)).main_scout_coverage == 1.0


def test_the_opening_record_freezes_once_the_opening_is_over() -> None:
    watch = OpeningWatch(window=300.0)
    watch.observe(frame(120.0, visible=(ENEMY_NATURAL,)))

    late = watch.observe(frame(400.0, visible=(ENEMY_THIRD,), enemy=()))

    assert late.third.status is ExpansionStatus.UNKNOWN
    assert late.last_updated == 120.0


def test_a_random_opponent_keeps_the_race_its_units_gave_away() -> None:
    watch = OpeningWatch()

    watch.observe(frame(60.0, race=Race.Random))
    known = watch.observe(frame(70.0, race=Race.Zerg))
    later = watch.observe(frame(80.0, race=Race.Random))

    assert (known.enemy_race, known.race_known) == (Race.Zerg, True)
    assert later.enemy_race is Race.Zerg


# --- AWARENESS: what the facts mean ----------------------------------------


def observations(race: Race = Race.Protoss, **kwargs) -> OpeningObservations:
    base = {"enemy_race": race, "main_scout_coverage": 0.8, "last_updated": 120.0}
    structures = kwargs.pop("seen", {})
    return OpeningObservations(
        structures=tuple(
            (type_id, StructureObservation(count, at, at))
            for type_id, (count, at) in sorted(structures.items(), key=lambda i: i[0].name)
        ),
        **{**base, **kwargs},
    )


def expansion(status: ExpansionStatus, at: float) -> ExpansionObservation:
    if status is ExpansionStatus.PRESENT:
        return ExpansionObservation(status, last_checked_at=at, first_seen_at=at)
    if status is ExpansionStatus.ABSENT_CONFIRMED:
        return ExpansionObservation(status, last_checked_at=at, absent_at=at)
    return ExpansionObservation()


def test_an_opening_nobody_scouted_is_no_opening_at_all() -> None:
    belief = read_opening(OpeningObservations(), now=120.0)

    assert (belief.aggression, belief.greed, belief.tech, belief.proxy) == (0.0, 0.0, 0.0, 0.0)
    assert (belief.confidence, belief.observed) == (0.0, False)


def test_an_expansion_nobody_checked_never_reads_as_a_late_expansion() -> None:
    unchecked = read_opening(observations(), now=200.0)
    absent = read_opening(
        observations(natural=expansion(ExpansionStatus.ABSENT_CONFIRMED, 175.0)), now=200.0
    )

    assert unchecked.term("natural_delay") == 0.0
    assert absent.term("natural_delay") == 1.0
    assert absent.aggression > unchecked.aggression


def test_aggression_rises_with_a_late_natural_and_more_production() -> None:
    late = observations(
        natural=expansion(ExpansionStatus.ABSENT_CONFIRMED, 165.0),
        seen={UnitTypeId.GATEWAY: (3, 105.0)},
    )
    standard = observations(
        natural=expansion(ExpansionStatus.PRESENT, 95.0),
        seen={UnitTypeId.GATEWAY: (1, 105.0)},
    )

    aggressive = read_opening(late, now=170.0)
    normal = read_opening(standard, now=170.0)

    assert aggressive.aggression > 0.6
    assert aggressive.aggression > normal.aggression
    assert aggressive.greed < normal.greed
    # Nothing was added up to one: the scores are independent.
    assert aggressive.aggression + aggressive.greed + aggressive.tech != pytest.approx(1.0)


def test_greed_rises_with_an_early_natural_and_an_early_third() -> None:
    natural_only = observations(natural=expansion(ExpansionStatus.PRESENT, 90.0))
    both = observations(
        natural=expansion(ExpansionStatus.PRESENT, 90.0),
        third=expansion(ExpansionStatus.PRESENT, 235.0),
    )

    one = read_opening(natural_only, now=240.0)
    two = read_opening(both, now=240.0)

    assert two.greed > one.greed > 0.4
    assert two.aggression < 0.2


def test_tech_rises_with_gas_and_tech_structures_and_a_delayed_third() -> None:
    plain = observations(seen={UnitTypeId.GATEWAY: (2, 100.0)})
    teching = observations(
        gases_seen=3,
        third=expansion(ExpansionStatus.ABSENT_CONFIRMED, 330.0),
        seen={
            UnitTypeId.GATEWAY: (1, 100.0),
            UnitTypeId.CYBERNETICSCORE: (1, 130.0),
            UnitTypeId.STARGATE: (1, 200.0),
        },
    )

    assert read_opening(teching, now=330.0).tech > read_opening(plain, now=330.0).tech
    assert read_opening(teching, now=330.0).tech > 0.6


def test_proxy_rises_when_a_well_scouted_main_lacks_what_belongs_in_it() -> None:
    scouted = observations(
        main_scout_coverage=0.9,
        last_updated=170.0,
        natural=expansion(ExpansionStatus.ABSENT_CONFIRMED, 170.0),
    )
    glanced = replace(scouted, main_scout_coverage=0.1)
    with_gateway = replace(
        scouted, structures=((UnitTypeId.GATEWAY, StructureObservation(1, 100.0, 100.0)),)
    )

    missing = read_opening(scouted, now=175.0)

    assert missing.proxy > 0.5
    assert missing.proxy > read_opening(glanced, now=175.0).proxy
    assert missing.proxy > read_opening(with_gateway, now=175.0).proxy


def test_a_structure_on_our_half_is_the_strongest_proxy_evidence() -> None:
    caught = observations(proxy_structures_seen=1, seen={UnitTypeId.BARRACKS: (1, 90.0)})

    assert read_opening(caught, now=95.0).proxy > 0.8


def test_confidence_follows_coverage_checks_and_how_fresh_the_record_is() -> None:
    thorough = observations(
        main_scout_coverage=0.9,
        natural=expansion(ExpansionStatus.PRESENT, 95.0),
        third=expansion(ExpansionStatus.ABSENT_CONFIRMED, 160.0),
        gases_seen=2,
        seen={UnitTypeId.GATEWAY: (2, 100.0), UnitTypeId.CYBERNETICSCORE: (1, 130.0)},
        last_updated=160.0,
    )
    glance = replace(thorough, main_scout_coverage=0.1, third=ExpansionObservation())

    fresh = read_opening(thorough, now=170.0)
    thin = read_opening(glance, now=170.0)
    stale = read_opening(thorough, now=400.0)

    assert fresh.confidence > 0.7
    assert thin.confidence < fresh.confidence
    assert stale.confidence < 0.4 * fresh.confidence
    # What was observed still reads the same; only its worth decayed.
    assert stale.greed == fresh.greed


def test_an_unknown_race_is_read_with_middle_expectations_and_less_confidence() -> None:
    facts = {
        "natural": expansion(ExpansionStatus.PRESENT, 95.0),
        "main_scout_coverage": 0.8,
        "seen": {UnitTypeId.GATEWAY: (1, 100.0)},
    }
    known = read_opening(observations(Race.Protoss, **facts), now=120.0)
    unknown = read_opening(observations(Race.Random, **facts), now=120.0)

    assert unknown.confidence < known.confidence
    # And nothing is expected of a main whose race we do not know.
    assert unknown.proxy == 0.0


def test_every_race_reads_the_same_natural_differently() -> None:
    at = expansion(ExpansionStatus.PRESENT, 100.0)
    greed = {
        race: read_opening(observations(race, natural=at), now=120.0).greed
        for race in (Race.Zerg, Race.Protoss, Race.Terran)
    }

    # A hatchery at 1:40 is late for a Zerg and early for a Terran.
    assert greed[Race.Zerg] < greed[Race.Protoss] < greed[Race.Terran]
    assert expectations_for(Race.Zerg).third_late < expectations_for(Race.Terran).third_late
    assert expectations_for(Race.Random).expected_in_main == frozenset()


def test_the_third_window_of_each_race_moves_the_delay_it_reads() -> None:
    absent = expansion(ExpansionStatus.ABSENT_CONFIRMED, 250.0)
    delay = {
        race: read_opening(observations(race, third=absent), now=260.0).term("third_delay")
        for race in (Race.Zerg, Race.Protoss, Race.Terran)
    }

    # A third still missing at 4:10 is late for a Zerg and on time for a Terran.
    assert delay[Race.Zerg] > delay[Race.Protoss] > 0.0
    assert delay[Race.Terran] == 0.0


def test_the_scores_stay_inside_their_range_however_much_is_seen() -> None:
    everything = observations(
        natural=expansion(ExpansionStatus.ABSENT_CONFIRMED, 300.0),
        third=expansion(ExpansionStatus.ABSENT_CONFIRMED, 300.0),
        gases_seen=8,
        workers_seen=40,
        early_combat_units_seen=30,
        proxy_structures_seen=4,
        main_scout_coverage=1.0,
        seen={type_id: (6, 60.0) for type_id in expectations_for(Race.Protoss).tech},
    )

    belief = read_opening(everything, now=305.0)

    for score in (belief.aggression, belief.greed, belief.tech, belief.proxy, belief.confidence):
        assert 0.0 <= score <= 1.0


def test_the_config_rejects_spans_that_cannot_divide() -> None:
    with pytest.raises(ValueError):
        OpeningBeliefConfig(gas_span=0.0)


def test_awareness_publishes_the_read_of_the_frames_opening_record() -> None:
    watch = OpeningWatch()
    state = frame(
        120.0,
        visible=(ENEMY_NATURAL,),
        enemy=(structure(7, UnitTypeId.NEXUS, ENEMY_NATURAL),),
    )
    carried = replace(state, enemy_opening=watch.observe(state))

    belief = AwarenessModel().infer(carried).opening

    assert belief.race is Race.Protoss
    assert belief.greed > 0.0 and belief.confidence > 0.0


# --- INTEL: the scout that goes and gets them ------------------------------


def scv(tag: int, x: float = 12.0, y: float = 8.0, *, role: str = SCOUTING):
    return unit(tag, UnitTypeId.SCV, x, y, worker=True, role=role)


def mission(now: float = 50.0, **kwargs) -> EarlyScoutMission:
    route = scouting_route(OPENING_MAP)
    return EarlyScoutMission(
        "intel:early_scout:1",
        route,
        now,
        natural=ENEMY_NATURAL,
        third=ENEMY_THIRD,
        proxy_route=proxy_route(OPENING_MAP),
        watchpoints=enemy_exits(OPENING_MAP),
        **kwargs,
    )


def step(scout: EarlyScoutMission, state, seen=frozenset()):
    from bot.ego.missions import MissionFeedback

    return scout.step(state, seen, MissionFeedback())


def scouting(time: float, *, opening: OpeningObservations | None = None, **kwargs):
    state = frame(time, own_units=(scv(100),), **kwargs)
    return state if opening is None else replace(state, enemy_opening=opening)


def test_the_scout_asks_for_an_scv_and_checks_the_natural_before_the_main() -> None:
    scout = mission()

    (asking,) = step(scout, frame(50.0))
    assert (scout.phase, asking.count, asking.unit_types) == (
        ScoutPhase.REQUESTING,
        1,
        frozenset({UnitTypeId.SCV}),
    )
    assert (asking.command, asking.target) == (Command.SCOUT, ENEMY_NATURAL)

    (checking,) = step(scout, scouting(51.0))
    assert (scout.phase, scout.set_out, checking.target) == (
        ScoutPhase.CHECK_NATURAL,
        51.0,
        ENEMY_NATURAL,
    )


def test_the_lifecycle_walks_the_whole_opening_and_then_keeps_watching() -> None:
    watch = OpeningWatch()
    scout = mission()
    main = [LATTICE[index] for index in ENEMY_MAIN]
    phases = []

    def advance(time: float, *, visible=(), enemy=(), seen=frozenset()):
        state = scouting(time, visible=visible, enemy=enemy)
        state = replace(state, enemy_opening=watch.observe(state))
        proposals = step(scout, state, seen)
        phases.append(scout.phase)
        return proposals

    advance(51.0)
    # The natural is empty: on to the main.
    advance(91.0, visible=(ENEMY_NATURAL,))
    assert scout.phase is ScoutPhase.ENTER_MAIN

    advance(100.0, visible=(MAP.enemy_start,))
    assert scout.phase is ScoutPhase.CIRCLE_MAIN

    # The lap is done, and the natural was empty long enough to be worth a
    # second look.
    lapped = advance(130.0, visible=main, seen=frozenset(range(len(scout.route))))
    assert scout.phase is ScoutPhase.RECHECK_NATURAL
    assert lapped[0].target == ENEMY_NATURAL

    advance(150.0, visible=(ENEMY_NATURAL,), enemy=(structure(7, UnitTypeId.NEXUS, ENEMY_NATURAL),))
    assert (scout.phase, scout.reason) == (ScoutPhase.CHECK_THIRD, "natural_found")

    advance(
        200.0, visible=(ENEMY_THIRD,), enemy=(structure(8, UnitTypeId.NEXUS, ENEMY_THIRD),)
    )
    assert (scout.phase, scout.status, scout.reason) == (
        ScoutPhase.SURVEIL,
        MissionStatus.ACTIVE,
        "third_found",
    )

    # The round runs until the opening is over, and then it is over.
    assert step(scout, scouting(scout.window.until)) == ()
    assert (scout.status, scout.reason) == (MissionStatus.COMPLETED, "opening_over")
    assert step(scout, scouting(310.0)) == ()
    assert phases[0] is ScoutPhase.CHECK_NATURAL


def walk_to_the_third(scout: EarlyScoutMission, watch: OpeningWatch):
    """Drive a mission to CHECK_THIRD the way a game would, and hand back the
    step that keeps driving it."""

    def advance(time: float, *, visible=(), enemy=(), seen=frozenset()):
        state = scouting(time, visible=visible, enemy=enemy)
        return step(scout, replace(state, enemy_opening=watch.observe(state)), seen)

    nexus = structure(7, UnitTypeId.NEXUS, ENEMY_NATURAL)
    advance(51.0)
    # The natural was already standing, so there is nothing to recheck.
    advance(91.0, visible=(ENEMY_NATURAL,), enemy=(nexus,))
    advance(100.0, visible=(MAP.enemy_start,))
    advance(130.0, seen=frozenset(range(len(scout.route))))
    assert scout.phase is ScoutPhase.CHECK_THIRD
    return advance


def test_an_empty_third_starts_the_round_instead_of_parking_on_it() -> None:
    watch, scout = OpeningWatch(), mission()
    advance = walk_to_the_third(scout, watch)

    # It gets to the third and finds nothing there.
    (looking,) = advance(150.0, visible=(ENEMY_THIRD,))

    assert (scout.phase, scout.reason) == (ScoutPhase.SURVEIL, "third_empty")
    assert watch.observations.third.status is ExpansionStatus.ABSENT_CONFIRMED
    # An answer it already has is not worth standing on.
    assert looking.target != ENEMY_THIRD
    assert looking.target in scout.ring


def test_the_round_comes_back_to_the_third_and_never_stands_still() -> None:
    watch = OpeningWatch()
    scout = mission(window=replace(ScoutWindow(), surveil_step=5.0))
    advance = walk_to_the_third(scout, watch)
    (looking,) = advance(150.0, visible=(ENEMY_THIRD,))

    # Every place it is sent to, it reaches: the round rotates.
    targets = []
    time = 150.0
    for _ in range(10):
        time += 5.0
        (looking,) = advance(time, visible=(looking.target,))
        targets.append(looking.target)

    # It reaches the last place it was sent to as well.
    advance(time + 5.0, visible=(looking.target,))

    assert set(targets) <= set(scout.ring)
    assert all(before != after for before, after in zip(targets, targets[1:], strict=False))
    # Both expansions come round again on their own ...
    assert ENEMY_THIRD in targets and ENEMY_NATURAL in targets
    # ... and looking again is what the record keeps.
    assert watch.observations.third.last_checked_at > 150.0
    assert scout.status is MissionStatus.ACTIVE


def test_a_place_the_round_cannot_reach_does_not_hold_it_up() -> None:
    watch = OpeningWatch()
    scout = mission(window=replace(ScoutWindow(), surveil_step=5.0))
    advance = walk_to_the_third(scout, watch)
    (looking,) = advance(150.0, visible=(ENEMY_THIRD,))
    blocked = looking.target

    # Nothing ever comes into vision: it waits its step and goes round anyway.
    assert advance(153.0)[0].target == blocked
    assert advance(156.0)[0].target != blocked


def test_what_shows_up_after_the_first_check_is_still_recorded() -> None:
    watch = OpeningWatch()
    scout = mission(window=replace(ScoutWindow(), surveil_step=5.0))
    advance = walk_to_the_third(scout, watch)
    advance(150.0, visible=(ENEMY_THIRD,))
    assert scout.phase is ScoutPhase.SURVEIL

    # A Stargate goes up in the main, and the third finally appears.
    advance(200.0, visible=(MAP.enemy_start,),
            enemy=(structure(20, UnitTypeId.STARGATE, MAP.enemy_start),))
    advance(230.0, visible=(ENEMY_THIRD,),
            enemy=(structure(21, UnitTypeId.NEXUS, ENEMY_THIRD),))

    observed = watch.observations
    assert observed.structure(UnitTypeId.STARGATE).first_seen_at == 200.0
    assert observed.third.status is ExpansionStatus.PRESENT
    assert observed.third.appeared_between == (150.0, 230.0)
    # The patrol goes on; the read of it is Awareness' job.
    assert scout.status is MissionStatus.ACTIVE
    assert read_opening(observed, now=230.0).tech > 0.0


def test_the_round_ends_with_the_opening_window() -> None:
    watch = OpeningWatch()
    scout = mission()
    advance = walk_to_the_third(scout, watch)
    advance(150.0, visible=(ENEMY_THIRD,))
    assert scout.phase is ScoutPhase.SURVEIL

    assert advance(scout.window.until - 1.0) != ()
    assert advance(scout.window.until) == ()
    assert (scout.status, scout.reason) == (MissionStatus.COMPLETED, "opening_over")
    assert scout.report().phase == ScoutPhase.COMPLETE.value


def test_the_round_walks_the_expansions_the_way_out_and_the_main() -> None:
    scout = mission()
    exits = enemy_exits(OPENING_MAP)

    assert exits and set(exits) <= set(scout.ring)
    assert scout.ring[:2] == (ENEMY_NATURAL, ENEMY_THIRD)
    assert set(scouting_route(OPENING_MAP)[1:]) <= set(scout.ring)


def test_a_natural_already_standing_is_not_rechecked() -> None:
    watch = OpeningWatch()
    scout = mission()
    nexus = structure(7, UnitTypeId.NEXUS, ENEMY_NATURAL)

    def advance(time: float, *, visible=(), enemy=(), seen=frozenset()):
        state = scouting(time, visible=visible, enemy=enemy)
        step(scout, replace(state, enemy_opening=watch.observe(state)), seen)

    advance(51.0)
    advance(91.0, visible=(ENEMY_NATURAL,), enemy=(nexus,))
    advance(100.0, visible=(MAP.enemy_start,))
    advance(130.0, seen=frozenset(range(len(scout.route))))

    assert scout.phase is ScoutPhase.CHECK_THIRD


def test_a_phase_is_not_rushed_while_the_scout_is_still_walking() -> None:
    # A whole phase of walking across the map is not a phase standing still.
    scout = mission(window=ScoutWindow(check_for=10.0, travel_for=75.0))
    step(scout, scouting(51.0))

    step(scout, scouting(80.0))
    assert scout.phase is ScoutPhase.CHECK_NATURAL

    # Once it is there, the look has its own clock.
    at_the_natural = scv(100, ENEMY_NATURAL.x, ENEMY_NATURAL.y)
    step(scout, frame(85.0, own_units=(at_the_natural,)))
    assert scout.phase is ScoutPhase.CHECK_NATURAL
    step(scout, frame(96.0, own_units=(at_the_natural,)))
    assert (scout.phase, scout.reason) == (ScoutPhase.ENTER_MAIN, "check_timed_out")


def test_a_scout_that_never_reaches_the_main_still_moves_on() -> None:
    scout = mission(
        window=ScoutWindow(check_for=10.0, circle_for=10.0, travel_for=10.0, third_until=200.0)
    )
    step(scout, scouting(51.0))

    step(scout, scouting(62.0))
    assert (scout.phase, scout.reason) == (ScoutPhase.ENTER_MAIN, "check_timed_out")
    step(scout, scouting(73.0))
    assert (scout.phase, scout.reason) == (ScoutPhase.CIRCLE_MAIN, "entry_timed_out")
    step(scout, scouting(84.0))
    assert (scout.phase, scout.reason) == (ScoutPhase.CHECK_THIRD, "lap_timed_out")
    step(scout, scouting(201.0))
    assert (scout.phase, scout.reason) == (ScoutPhase.SURVEIL, "third_window_over")
    assert scout.status is MissionStatus.ACTIVE


def test_the_scout_fails_when_its_scv_is_lost_and_ends_when_the_opening_does() -> None:
    lost = mission()
    step(lost, scouting(51.0))

    assert step(lost, frame(60.0, own_units=(scv(100, role="GATHERING"),))) == ()
    assert (lost.status, lost.reason) == (MissionStatus.FAILED, "scout_lost")

    timed_out = mission(now=50.0, window=ScoutWindow(until=100.0))
    step(timed_out, scouting(51.0))
    assert step(timed_out, scouting(150.0)) == ()
    assert (timed_out.status, timed_out.reason) == (MissionStatus.COMPLETED, "opening_over")


def test_a_cancelled_scout_stops_proposing() -> None:
    scout = mission()
    step(scout, scouting(51.0))
    scout.request_cancel(CancelMode.IMMEDIATE, "home_threatened", 52.0)

    assert step(scout, scouting(52.0)) == ()
    assert (scout.status, scout.reason) == (MissionStatus.CANCELLED, "home_threatened")


def test_the_scout_walks_our_half_when_it_is_sent_after_a_proxy() -> None:
    scout = mission()
    step(scout, scouting(51.0))
    route = proxy_route(OPENING_MAP)
    assert route and all(
        point.distance_to(MAP.own_start) < point.distance_to(MAP.enemy_start) for point in route
    )

    assert scout.search_proxy("opening_reads_proxy", 60.0) is True
    (hunting,) = step(scout, scouting(60.0))

    assert (scout.phase, scout.reason) == (ScoutPhase.PROXY_SEARCH, "opening_reads_proxy")
    assert (hunting.target, hunting.priority) == (route[0], 1.0)
    assert scout.report().proxy_search is True

    # Each place looked at is crossed off; the search ends when they run out.
    assert step(scout, scouting(70.0, visible=route)) == ()
    assert (scout.status, scout.reason) == (MissionStatus.COMPLETED, "proxy_search_done")


def test_a_proxy_that_is_found_ends_the_search_at_once() -> None:
    scout = mission()
    step(scout, scouting(51.0))
    scout.search_proxy("opening_reads_proxy", 60.0)

    caught = replace(OpeningObservations(last_updated=61.0), proxy_structures_seen=1)
    assert step(scout, scouting(61.0, opening=caught)) == ()
    assert (scout.status, scout.reason) == (MissionStatus.COMPLETED, "proxy_found")


def test_a_terminal_scout_takes_no_further_orders() -> None:
    scout = mission()
    step(scout, scouting(51.0))
    scout.request_cancel(CancelMode.IMMEDIATE, "too_late", 52.0)
    step(scout, scouting(52.0))

    assert scout.search_proxy("opening_reads_proxy", 53.0) is False


# --- INTEL: the planner that owns it ---------------------------------------


def plan(planner: IntelPlanner, state):
    awareness = AwarenessModel().infer(state)
    intent = StrategyModel().decide(state, awareness)
    return planner.plan(state, awareness, intent)


def proxy_frame(time: float, **kwargs):
    """A frame whose opening record reads as a proxy: a well-scouted main with
    no Barracks in it."""

    observed = OpeningObservations(
        enemy_race=Race.Terran,
        natural=expansion(ExpansionStatus.ABSENT_CONFIRMED, time - 5.0),
        main_scout_coverage=1.0,
        proxy_structures_seen=0,
        last_updated=time - 1.0,
    )
    return replace(frame(time, race=Race.Terran, **kwargs), enemy_opening=observed)


def test_the_planner_sends_the_scout_after_a_proxy_when_awareness_believes_in_one() -> None:
    planner = IntelPlanner()
    plan(planner, frame(50.0))
    plan(planner, scouting(51.0))
    assert planner.mission.phase is ScoutPhase.CHECK_NATURAL

    state = proxy_frame(200.0, own_units=(scv(100),))
    belief = AwarenessModel().infer(state).opening
    assert belief.proxy >= PROXY_SEARCH_AT and belief.confidence >= PROXY_CONFIDENCE_AT

    (hunting,) = plan(planner, state).proposals

    assert planner.mission.phase is ScoutPhase.PROXY_SEARCH
    assert planner.proxy_search == 200.0
    assert hunting.target == proxy_route(OPENING_MAP)[0]
    assert plan(planner, state).scout.proxy_search is True


def test_a_quiet_opening_never_sends_the_scout_hunting() -> None:
    planner = IntelPlanner()
    plan(planner, frame(50.0))

    plan(planner, scouting(120.0))

    assert planner.mission.phase is not ScoutPhase.PROXY_SEARCH
    assert planner.proxy_search is None


def test_the_planner_reports_the_scout_every_frame() -> None:
    planner = IntelPlanner()

    report = plan(planner, frame(50.0)).scout

    assert (report.mission_id, report.phase, report.status) == (
        "intel:early_scout:1",
        ScoutPhase.REQUESTING.value,
        MissionStatus.ACTIVE.value,
    )
    assert report.target == ENEMY_NATURAL
    assert dict(report.inputs)["proxy_points"] > 0.0


def test_the_scout_window_follows_the_race_it_is_scouting() -> None:
    zerg = scout_window(frame(50.0, race=Race.Zerg))
    terran = scout_window(frame(50.0, race=Race.Terran))

    assert zerg.third_until == expectations_for(Race.Zerg).third_late
    assert terran.third_until > zerg.third_until
    assert terran.until <= 300.0


def test_no_scout_leaves_before_the_mineral_line_grows() -> None:
    planner = IntelPlanner()

    assert plan(planner, frame(50.0, workers=SCOUT_AT_WORKERS - 1)).proposals == ()
    assert planner.mission is None


# --- LOGS: the read a replay can be followed with -------------------------


def test_the_log_carries_every_step_of_the_opening_read() -> None:
    from bot.logs import Logs
    from bot.main import Layers, play_frame

    from .fakes import FakeLogger, FakeUnit
    from .test_frame_flow import build_bot

    bot = build_bot(attackers=0)
    # Sixteen workers put the scout on the road.
    bot.workers_in_gas = 12
    logger = FakeLogger()
    layers = Layers(map_view=MAP, logs=Logs(logger))
    natural = MAP.enemy_natural
    bot.state.visibility.data_numpy[int(natural.y), int(natural.x)] = 2

    bot.time = 60.0
    play_frame(bot, 0, layers)
    bot.time = 118.0
    bot.enemy_structures = [
        FakeUnit(500, UnitTypeId.HATCHERY, natural.x, natural.y, dps=0.0, structure=True)
    ]
    play_frame(bot, 1, layers)

    checked = logger.named("opening_scout.expansion_checked")
    assert [event["data"]["status"] for event in checked] == ["ABSENT_CONFIRMED", "PRESENT"]
    assert checked[1]["data"]["appeared_between"] == [60.0, 118.0]
    assert checked[0]["component"] == "attention"

    (seen,) = logger.named("opening_scout.structure_seen")
    assert (seen["data"]["structure"], seen["data"]["count_seen"]) == ("HATCHERY", 1)

    read = logger.named("awareness.opening_updated")[-1]["data"]
    assert read["race"] == "Zerg"
    assert read["natural"]["status"] == "PRESENT"
    assert set(read["belief"]) == {"aggression", "greed", "tech", "proxy", "confidence"}
    assert read["summary"].startswith("t=1:58 race=Zerg natural=PRESENT@1:58")

    phases = logger.named("opening_scout.phase_changed")
    assert phases[0]["data"]["phase"] == ScoutPhase.REQUESTING.value
    assert phases[0]["component"] == "missions"
    assert {event["data"]["mission_id"] for event in phases} == {"intel:early_scout:1"}


def test_the_log_says_when_the_scout_was_sent_after_a_proxy() -> None:
    from bot.logs import Logs

    from .fakes import FakeLogger

    logger = FakeLogger()
    logs = Logs(logger)
    planner = IntelPlanner()
    plan(planner, frame(50.0))
    state = proxy_frame(200.0, own_units=(scv(100),))
    awareness = AwarenessModel().infer(state)
    intel = planner.plan(state, awareness, StrategyModel().decide(state, awareness))

    logs.telemetry._record_scout(state.time, intel.scout)
    logs.telemetry._record_scout(state.time + 1.0, intel.scout)

    (started,) = logger.named("opening_scout.proxy_search_started")
    assert started["data"]["reason"] == "opening_reads_proxy"
    assert started["data"]["target"] is not None
    # Only the frame it was ordered writes it.
    assert len(logger.named("opening_scout.phase_changed")) == 1

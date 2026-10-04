from __future__ import annotations

from dataclasses import replace

import pytest
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import AMove, PathUnitToTarget
from ares.behaviors.macro import BuildStructure
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.awareness import AwarenessModel, OpeningBelief
from bot.body.behaviors import fortify, garrison, repair
from bot.body.engine import Engine
from bot.ego.planners import BunkerSite, Command, FortificationPlan, MissionStatus
from bot.ego.planners.defense import DefensePlanner, RushConfig
from bot.ego.planners.defense.missions import rush_defense
from bot.ego.planners.defense.policies.rush import bunker_site, read_rush
from bot.ego.strategy import StrategyModel
from bot.logs import Logs
from bot.main import Layers, play_frame

from .fakes import MAIN, MAP, NATURAL, FakeBot, FakeLogger, FakeUnit, attention, proposal, unit

NATURAL_SPOT = Point2((26.5, 17.5))


def zerglings(count: int, x: float, y: float, first: int = 900):
    return tuple(
        unit(first + index, UnitTypeId.ZERGLING, x + 0.5 * index, y, power=0.9, attack_air=False)
        for index in range(count)
    )


def bunker(tag: int = 50, x: float = 18.5, y: float = 18.5, *, ready=True, cargo=0, health=1.0):
    view = unit(tag, UnitTypeId.BUNKER, x, y, power=0.0, structure=True, ready=ready)
    return replace(view, health=health, cargo_used=cargo, cargo_max=4 if ready else 0)


def scvs(count: int, x: float = 12.0, y: float = 8.0, first: int = 100):
    return tuple(
        unit(first + index, UnitTypeId.SCV, x, y + index, power=0.6, worker=True, role="GATHERING")
        for index in range(count)
    )


class Game:
    """One planner over consecutive frames, as the bot runs it."""

    def __init__(self) -> None:
        self.awareness = AwarenessModel()
        self.strategy = StrategyModel()
        self.planner = DefensePlanner()

    def step(self, frame):
        awareness = self.awareness.infer(frame)
        intent = self.strategy.decide(frame, awareness)
        return awareness, self.planner.plan(frame, awareness, intent)

    def rush_view(self):
        return next(view for view in self.planner.views() if view.kind == rush_defense.KIND)


def by_command(plan, command: Command):
    return [item for item in plan.proposals if item.command is command]


# --- the reading ---


def test_the_rush_reading_combines_the_promise_and_the_attack_while_it_is_early() -> None:
    quiet = AwarenessModel().infer(attention(time=100.0))
    assert quiet.early_game == 1.0
    assert read_rush(quiet).level == 0.0

    promised = replace(quiet, opening=OpeningBelief(aggression=0.9, proxy=0.2, confidence=0.8))
    early = read_rush(promised)
    assert (early.expected, early.present, early.early_game) == pytest.approx((0.72, 0.0, 1.0))
    assert early.level == pytest.approx(0.72)
    # Half the early game left counts half; none left, nothing.
    assert read_rush(replace(promised, early_game=0.5)).level == pytest.approx(0.36)
    assert read_rush(replace(promised, early_game=0.0)).level == 0.0

    attacked = AwarenessModel().infer(attention(time=100.0, enemy_units=zerglings(6, 12, 10)))
    both = read_rush(replace(attacked, opening=promised.opening))
    assert both.present == pytest.approx(max(base.recent_threat for base in attacked.bases))
    assert both.level == pytest.approx(1.0 - (1.0 - 0.72) * (1.0 - both.present))


def test_the_early_game_ends_with_the_clock_or_a_third_base_and_never_returns() -> None:
    model = AwarenessModel()
    assert model.infer(attention(time=240.0)).early_game == 1.0
    assert model.infer(attention(time=330.0)).early_game == pytest.approx(0.5)
    # A third base ends it at once ...
    three = (MAIN, NATURAL, replace(MAIN, base_id="base:53:53", is_main=False))
    assert model.infer(attention(time=331.0, bases=three)).early_game == 0.0
    # ... and losing it does not bring the early game back.
    assert model.infer(attention(time=332.0)).early_game == 0.0
    assert AwarenessModel().infer(attention(time=600.0)).early_game == 0.0


def test_the_bunker_goes_in_front_of_the_natural_once_a_townhall_stands_there() -> None:
    one_base = attention(bases=(MAIN,))
    assert bunker_site(one_base) == BunkerSite(MAIN.base_id, MAP.own_start, MAP.main_ramp)

    solved = replace(MAP, bunker_sites=(NATURAL_SPOT, Point2((50.5, 50.5))))
    two_bases = attention(bases=(MAIN, NATURAL), map_view=solved)
    assert bunker_site(two_bases) == BunkerSite(NATURAL.base_id, NATURAL.position, NATURAL_SPOT)
    # Without a spot Ares solved, the Bunker goes by the natural's townhall.
    unsolved = attention(bases=(MAIN, NATURAL))
    assert bunker_site(unsolved).near == NATURAL.position
    assert bunker_site(attention(bases=())) is None


# --- the mission ---


def test_lings_at_the_main_early_open_a_rush_defense_that_wants_a_bunker() -> None:
    game = Game()
    frame = attention(
        time=120.0, own_units=(unit(1, x=20, y=20),), enemy_units=zerglings(6, 12, 10)
    )
    _, plan = game.step(frame)

    assert plan.fortification.bunkers == (BunkerSite(MAIN.base_id, MAP.own_start, MAP.main_ramp),)
    assert plan.fortification.reason == "rush_present"
    view = game.rush_view()
    assert (view.mission_id, view.phase, view.status) == (
        "defense:rush_defense:1",
        rush_defense.FORTIFY,
        MissionStatus.ACTIVE,
    )
    # The fight itself is the incident's.
    assert not by_command(plan, Command.GARRISON) and not by_command(plan, Command.REPAIR)
    assert by_command(plan, Command.ATTACK)


def test_a_quiet_game_or_a_late_attack_is_no_rush() -> None:
    game = Game()
    _, quiet = game.step(attention(time=120.0))
    assert quiet.fortification == FortificationPlan(
        reason="no_rush", inputs=game.planner.rush.inputs
    )
    _, late = Game().step(attention(time=500.0, enemy_units=zerglings(6, 12, 10)))
    assert late.fortification.bunkers == () and late.fortification.reason == "no_rush"


def test_a_bunker_being_built_is_waited_for_and_not_asked_again() -> None:
    game = Game()
    frame = attention(
        time=120.0,
        own_structures=(bunker(ready=False),),
        enemy_units=zerglings(6, 12, 10),
    )
    _, plan = game.step(frame)

    assert plan.fortification.bunkers == ()
    assert (game.rush_view().phase, game.rush_view().reason) == (
        rush_defense.FORTIFY,
        "bunker_building",
    )
    assert not by_command(plan, Command.GARRISON)


def test_a_ready_bunker_takes_the_nearest_marines_before_any_incident_does() -> None:
    game = Game()
    army = (
        unit(1, x=19, y=19),
        unit(2, x=20, y=19),
        unit(3, x=30, y=30),
        unit(4, x=21, y=21),
        unit(5, UnitTypeId.MARAUDER, 18, 18, power=1.6, attack_air=False),
    )
    frame = attention(
        time=120.0,
        own_units=army,
        own_structures=(bunker(cargo=1),),
        enemy_units=zerglings(6, 12, 10),
    )
    _, plan = game.step(frame)

    (fill,) = by_command(plan, Command.GARRISON)
    assert (fill.count, fill.unit_types, fill.target) == (
        3,
        frozenset({UnitTypeId.MARINE}),
        Point2((18.5, 18.5)),
    )
    assert fill.priority > max(item.priority for item in by_command(plan, Command.ATTACK))
    assert game.rush_view().phase == rush_defense.HOLD

    result = Engine().allocate(frame, plan.proposals)
    assert dict(result.owners)[1] == fill.proposal_id
    assert {tag for tag, owner in result.owners if owner == fill.proposal_id} == {1, 2, 4}
    # The Marauder takes no slot; the incident gets it and the far Marine.
    assert result.owner_of(5).startswith("defense:incident:")


@pytest.mark.parametrize(
    ("lings", "health", "repairers", "reason"),
    [
        (6, 1.0, 3, "bunker_attacked"),
        (20, 1.0, rush_defense.MAX_REPAIRERS, "bunker_attacked"),
        (6, 0.5, 3, "bunker_attacked"),
    ],
)
def test_scvs_repair_the_bunker_more_of_them_the_harder_it_is_attacked(
    lings: int, health: float, repairers: int, reason: str
) -> None:
    game = Game()
    frame = attention(
        time=120.0,
        own_units=scvs(8),
        own_structures=(bunker(cargo=4, health=health),),
        enemy_units=zerglings(lings, 16, 22),
    )
    awareness, plan = game.step(frame)

    (incident,) = awareness.incidents
    assert incident.center.distance_to(Point2((18.5, 18.5))) <= rush_defense.ATTACK_REACH
    (fix,) = by_command(plan, Command.REPAIR)
    assert (fix.count, fix.reason, fix.unit_types) == (
        repairers,
        reason,
        frozenset({UnitTypeId.SCV}),
    )
    assert not by_command(plan, Command.GARRISON)
    granted = Engine().allocate(frame, plan.proposals)
    assert len(next(grant for grant in granted.grants if grant.proposal is fix).tags) == repairers


def test_one_scv_mends_a_damaged_bunker_and_none_stays_by_a_whole_one() -> None:
    game = Game()
    game.step(
        attention(time=120.0, own_structures=(bunker(cargo=4),), enemy_units=zerglings(6, 12, 10))
    )
    # The lings are gone; the base still remembers them, so the rush is on.
    _, damaged = game.step(
        attention(
            time=121.0,
            own_units=scvs(4),
            own_structures=(bunker(cargo=4, health=0.6),),
            dead_tags=range(900, 906),
        )
    )
    (fix,) = by_command(damaged, Command.REPAIR)
    assert (fix.count, fix.reason) == (1, "bunker_damaged")

    _, whole = game.step(
        attention(time=122.0, own_units=scvs(4), own_structures=(bunker(cargo=4),))
    )
    assert not by_command(whole, Command.REPAIR)


def test_the_rush_is_over_once_it_reads_so_and_the_garrison_walks_out() -> None:
    game = Game()
    held = (bunker(cargo=3),)
    game.step(attention(time=120.0, own_structures=held, enemy_units=zerglings(6, 12, 10)))

    # The lings are dead, but the base still remembers them: still a rush.
    _, after = game.step(attention(time=125.0, own_structures=held, dead_tags=range(900, 906)))
    assert game.rush_view().status is MissionStatus.ACTIVE
    assert after.fortification.unload == ()

    _, over = game.step(attention(time=200.0, own_structures=held))
    view = game.rush_view()
    assert (view.status, view.reason) == (MissionStatus.COMPLETED, "rush_over")
    assert over.fortification.unload == (50,)
    assert game.planner.rush_defense is None


def test_no_rush_defense_outlives_the_early_game_even_under_attack() -> None:
    game = Game()
    held = (bunker(cargo=3),)
    lings = zerglings(6, 12, 10)
    game.step(attention(time=120.0, own_structures=held, enemy_units=lings))

    _, pressed = game.step(attention(time=430.0, own_structures=held, enemy_units=lings))
    view = game.rush_view()
    assert (view.status, view.reason) == (MissionStatus.COMPLETED, "early_game_over")
    assert pressed.fortification.unload == (50,)
    # The attack goes on, and it is the incidents' alone: no rush opens again.
    _, later = game.step(attention(time=431.0, own_structures=held, enemy_units=lings))
    assert later.fortification.reason == "no_rush"
    assert by_command(later, Command.ATTACK)
    assert not by_command(later, Command.GARRISON) and not by_command(later, Command.REPAIR)


def test_ten_minutes_in_on_six_bases_nothing_is_a_rush() -> None:
    game = Game()
    bases = tuple(replace(MAIN, base_id=f"base:{index}", is_main=index == 0) for index in range(6))
    _, plan = game.step(attention(time=600.0, bases=bases, enemy_units=zerglings(20, 12, 10)))
    assert game.planner.rush.level == 0.0
    assert plan.fortification.bunkers == () and plan.fortification.reason == "no_rush"
    assert all(view.kind != rush_defense.KIND for view in game.planner.views())


def test_losing_the_held_base_fails_the_defense_and_a_new_one_holds_the_main() -> None:
    game = Game()
    solved = replace(MAP, bunker_sites=(NATURAL_SPOT,))
    # Between the two bases: once the natural falls, they press the main.
    lings = zerglings(6, 22, 14)
    _, first = game.step(
        attention(time=150.0, bases=(MAIN, NATURAL), map_view=solved, enemy_units=lings)
    )
    assert first.fortification.bunkers[0].site_id == NATURAL.base_id

    _, lost = game.step(attention(time=151.0, bases=(MAIN,), map_view=solved, enemy_units=lings))
    failed, opened = [view for view in game.planner.views() if view.kind == rush_defense.KIND]
    assert (failed.mission_id, failed.status, failed.reason) == (
        "defense:rush_defense:1",
        MissionStatus.FAILED,
        "base_lost",
    )
    assert opened.mission_id == "defense:rush_defense:2"
    assert lost.fortification.bunkers == (BunkerSite(MAIN.base_id, MAP.own_start, MAP.main_ramp),)


# --- the behaviors ---


def fake_bunker(tag: int = 50, *, cargo: int = 1, ready: bool = True, health: float = 400.0):
    return FakeUnit(
        tag,
        UnitTypeId.BUNKER,
        18.5,
        18.5,
        dps=0.0,
        hit_points=400.0,
        health=health,
        structure=True,
        ready=ready,
        cargo_used=cargo,
        cargo_max=4,
    )


def test_a_garrisoned_marine_is_ordered_into_the_bunker_once() -> None:
    bot = FakeBot()
    held = fake_bunker()
    bot.structures = [held]
    walking = FakeUnit(1, UnitTypeId.MARINE, 22, 22)
    entering = FakeUnit(
        2, UnitTypeId.MARINE, 20, 20, orders=[type("Order", (), {"target": held.tag})()]
    )
    order = proposal(
        "defense:rush_defense:1:garrison", 1.0, command=Command.GARRISON, target=held.position
    )

    garrison.execute(bot, [walking, entering], order)

    assert walking.commands == [(AbilityId.SMART, held)]
    assert entering.commands == []
    assert bot.registered == []


def test_with_no_bunker_to_enter_a_garrison_fights_at_the_target() -> None:
    bot = FakeBot()
    bot.structures = [fake_bunker(cargo=4)]
    marine = FakeUnit(1, UnitTypeId.MARINE, 22, 22)

    garrison.execute(
        bot, [marine], proposal("x", 1.0, command=Command.GARRISON, target=Point2((18.5, 18.5)))
    )

    assert marine.commands == []
    (fight,) = bot.registered
    assert isinstance(fight, CombatManeuver) and isinstance(fight.micros[-1], AMove)


def test_a_repairer_leaves_mining_and_mends_the_most_damaged_first() -> None:
    bot = FakeBot()
    held = fake_bunker(health=200.0)
    command_center = FakeUnit(
        1,
        UnitTypeId.COMMANDCENTER,
        20.5,
        20.5,
        dps=0.0,
        hit_points=1500.0,
        health=1000.0,
        structure=True,
    )
    hurt_scv = FakeUnit(3, UnitTypeId.SCV, 19, 19, dps=5.0, health=10.0, mechanical=True)
    scv = FakeUnit(2, UnitTypeId.SCV, 17, 17, dps=5.0, mechanical=True)
    bot.structures = [command_center, held]
    bot.units = [scv, hurt_scv]
    order = proposal("x", 1.0, command=Command.REPAIR, target=held.position)

    repair.execute(bot, [scv], order)

    assert scv.commands == [(AbilityId.EFFECT_REPAIR, held)]
    assert bot.mediator.role_of(2) == "REPAIRING"
    assert bot.mediator.removed_from_minerals == [2]

    # Nothing left to mend: it waits by the target.
    held.health, command_center.health = held.health_max, command_center.health_max
    scv.commands = []
    repair.execute(bot, [scv], order)
    assert scv.commands == []
    (wait,) = bot.registered
    assert isinstance(wait, PathUnitToTarget) and wait.target == held.position


def test_a_bunker_is_built_where_the_plan_says_once_it_is_affordable_and_unloads_on_request() -> (
    None
):
    site = BunkerSite("base:30:12", NATURAL.position, NATURAL_SPOT)
    bot = FakeBot()
    full = fake_bunker(cargo=3)
    empty = fake_bunker(51, cargo=0)
    bot.structures = [full, empty]

    report = fortify.execute(bot, FortificationPlan(bunkers=(site,), unload=(50, 51)))

    (build,) = bot.registered
    assert isinstance(build, BuildStructure)
    assert (build.base_location, build.structure_id, build.closest_to) == (
        NATURAL.position,
        UnitTypeId.BUNKER,
        NATURAL_SPOT,
    )
    assert (build.production, build.find_alternative) == (False, False)
    assert full.commands == [AbilityId.UNLOADALL_BUNKER] and empty.commands == []
    assert report == fortify.FortifyReport(building=("BUNKER",), unloaded=(50,))

    bot.registered, bot.minerals = [], fortify.BUNKER_COST - 1
    assert fortify.execute(bot, FortificationPlan(bunkers=(site,))).building == ()
    assert bot.registered == []


def test_a_rush_at_home_asks_ares_for_a_bunker_and_the_log_says_why() -> None:
    logger = FakeLogger()
    bot = FakeBot()
    bot.time = 120.0
    command_center = FakeUnit(
        1, UnitTypeId.COMMANDCENTER, 10.5, 10.5, dps=0.0, hit_points=1500.0, structure=True
    )
    bot.structures = [command_center]
    bot.townhalls = [command_center]
    bot.units = [FakeUnit(200, UnitTypeId.MARINE, 18, 18)]
    bot.enemy_units = [
        FakeUnit(900 + index, UnitTypeId.ZERGLING, 14 + index, 12, hit_points=35.0)
        for index in range(6)
    ]
    layers = Layers(map_view=MAP, logs=Logs(logger))

    frame = play_frame(bot, 0, layers)

    assert frame.fortification.bunkers[0].site_id == MAIN.base_id
    assert frame.fortified.building == ("BUNKER",)
    assert any(isinstance(item, BuildStructure) for item in bot.registered)
    (planned,) = logger.named("planner.fortification_planned")
    assert planned["data"]["reason"] == "rush_present"
    assert planned["data"]["building"] == ["BUNKER"]
    assert planned["data"]["inputs"]["rush"] >= RushConfig().open_at
    (opened,) = [
        view
        for event in logger.named("mission.updated")
        for view in event["data"]["missions"]
        if view["kind"] == rush_defense.KIND
    ]
    assert opened["phase"] == rush_defense.FORTIFY

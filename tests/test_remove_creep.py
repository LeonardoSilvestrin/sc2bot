"""A noncombat map-control operation, from region ranking to production and grants."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from ares.behaviors.combat.individual import PathUnitToTarget
from ares.behaviors.macro import BuildStructure, MacroPlan, SpawnController, TechUp
from ares.build_runner.build_order_parser import BuildOrderParser
from sc2.data import Race
from sc2.game_data import Cost
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from bot.awareness import AwarenessModel
from bot.body import behaviors
from bot.body.behaviors import economy as buying
from bot.body.behaviors import remove_creep
from bot.body.engine import Engine
from bot.ego import economy
from bot.ego.economy.contracts import UnitRequest
from bot.ego.economy.knowledge.styles import BIO, MECH
from bot.ego.planners import CancelMode, Command, MissionFeedback, MissionStatus
from bot.ego.planners.map_control import MapControlPlanner
from bot.ego.planners.map_control.missions.remove_creep import CreepPhase
from bot.ego.strategy import StrategicPosture, StrategyModel
from bot.logs import Logs
from bot.main import Layers, play_frame

from .fakes import MAP, FakeBot, FakeLogger, FakeUnit, attention, proposal, seen_everywhere, unit
from .test_behaviors import ProductionBot
from .test_economy import Barracks

REGIONS = tuple(
    replace(
        region,
        sample_indices=tuple(
            i
            for i, p in enumerate(MAP.lattice)
            if (p.x < 20 if index == 0 else 20 <= p.x < 44 if index == 1 else p.x >= 44)
        ),
    )
    for index, region in enumerate(MAP.topology.regions)
)
CREEP_MAP = replace(MAP, topology=replace(MAP.topology, regions=REGIONS))
RAVEN = UnitRequest(UnitTypeId.RAVEN, 1, "remove_creep:1", "creep_detection")


def frame(*, mech=False, **kwargs):
    escorts = tuple(
        unit(i, UnitTypeId.HELLION if mech else UnitTypeId.MARINE, 18, 18) for i in range(1, 5)
    )
    army = (unit(10, UnitTypeId.RAVEN, 18, 18, power=0, flying=True), *escorts)
    if not mech:
        army += (unit(11, UnitTypeId.MEDIVAC, 18, 18, power=0, flying=True),)
    creep = np.zeros((64, 64), dtype=np.uint8)
    creep[10:19, 24:40] = 1
    kwargs.setdefault("own_units", army)
    return replace(
        attention(enemy_race=Race.Zerg, map_view=CREEP_MAP, visibility=seen_everywhere(), **kwargs),
        creep=creep,
    )


def plan(planner, current, feedback=None, belief=None, posture=StrategicPosture.DEVELOP):
    belief = belief or AwarenessModel().infer(current)
    intent = replace(StrategyModel().decide(current, belief), posture=posture)
    return planner.plan(current, belief, intent, feedback)


def clearing(*, mech=False):
    planner, engine, current = MapControlPlanner(), Engine(), frame(mech=mech)
    first = plan(planner, current)
    grants = engine.allocate(current, first.proposals)
    second = plan(planner, current, grants)
    assert planner.mission.phase is CreepPhase.CLEAR
    return planner, engine, current, second, engine.allocate(current, second.proposals)


@pytest.mark.parametrize("race", [Race.Terran, Race.Protoss, Race.Random, Race.NoRace])
def test_only_zerg_opens_the_operation(race):
    planner = MapControlPlanner()
    planned = plan(planner, replace(frame(), enemy_race=race))
    assert planner.mission is None and planner.views() == () and planned.unit_requests == ()
    assert len(planned.proposals) == 1


def test_detector_is_requested_during_the_opening_without_taking_escort_before_it_exists():
    current = frame(opening_done=False, own_units=(unit(1), unit(2)))
    planner = MapControlPlanner()
    planned = plan(planner, current)
    belief = AwarenessModel().infer(current)
    intent = StrategyModel().decide(current, belief)
    bought = economy.plan(current, intent, awareness=belief, unit_requests=planned.unit_requests)
    assert not bought.active and bought.unit_requests == (RAVEN,)
    assert len(planned.proposals) == 1  # the escort stays available until the Raven exists
    assert all(kind is not UnitTypeId.RAVEN for kind, _, _ in bought.composition)


@pytest.mark.parametrize("mech", [False, True])
def test_one_detector_and_bounded_escort_clear_a_ranked_region(mech):
    planner, _, current, planned, result = clearing(mech=mech)
    assert planner.mission.region == "region:1"
    assert current.has_creep(planner.mission.target)
    granted = [g for g in result.grants if g.proposal.mission_id]
    assert next(g.tags for g in granted if "raven" in g.proposal.proposal_id) == (10,)
    assert len(next(g.tags for g in granted if "escort" in g.proposal.proposal_id)) == (
        2 if mech else 4
    )
    assert any("medivac" in g.proposal.proposal_id for g in granted) is not mech
    assert all(g.proposal.command is Command.REMOVE_CREEP for g in granted)
    assert planned.unit_requests == (RAVEN,)


def test_no_creep_releases_the_escort_but_keeps_the_raven():
    planner, _, current, _, feedback = clearing()
    current = replace(current, creep=np.zeros((64, 64), dtype=np.uint8))
    planned = plan(planner, current, feedback)
    assert planner.mission.phase is CreepPhase.WAIT
    assert [p.unit_types for p in planned.proposals if p.mission_id] == [
        frozenset({UnitTypeId.RAVEN})
    ]


def test_a_lost_detector_is_replaced_and_the_escort_is_released():
    planner, _, current, _, feedback = clearing()
    lost = replace(current, own_units=tuple(u for u in current.own_units if u.tag != 10))
    planned = plan(planner, lost, feedback)
    assert planned.unit_requests == (RAVEN,)
    assert not any(p.mission_id for p in planned.proposals)


def test_enemy_presence_withdraws_the_whole_squad_and_holds_a_cooldown():
    planner, _, current, _, feedback = clearing()
    threatened = replace(current, time=2, enemy_units=(unit(90, UnitTypeId.ZERGLING, 20, 18),))
    planned = plan(planner, threatened, feedback)
    assert planner.mission.phase is CreepPhase.RETREAT
    assert all(
        p.target == planned.anchor and dict(p.inputs)["clear"] == 0
        for p in planned.proposals
        if p.mission_id
    )
    plan(planner, replace(current, time=3), feedback)
    assert planner.mission.phase is CreepPhase.RETREAT


def test_dangerous_regions_and_closed_routes_are_not_cleaned():
    planner, _, current, _, feedback = clearing()
    belief = AwarenessModel().infer(current)
    hot = replace(belief, regions=tuple(replace(r, threat=0.9) for r in belief.regions))
    plan(planner, current, feedback, belief=hot)
    assert planner.mission.phase is CreepPhase.WAIT
    blocked = replace(
        current.map.topology,
        passages=tuple(replace(p, state="closed") for p in current.map.topology.passages),
    )
    plan(planner, replace(current, map=replace(current.map, topology=blocked)), feedback)
    assert planner.mission.phase is CreepPhase.WAIT


def test_searching_empty_creep_moves_to_another_point_instead_of_parking_forever():
    planner, _, current, _, feedback = clearing()
    target = planner.mission.target
    arrived = replace(
        current, time=1, own_units=tuple(replace(u, position=target) for u in current.own_units)
    )
    plan(planner, arrived, feedback)
    assert planner.mission.target != target and planner.mission.phase is CreepPhase.CLEAR


def test_a_fully_searched_front_waits_without_repeatedly_reclaiming_the_escort():
    planner, engine, current = MapControlPlanner(), Engine(), frame()
    creep = np.zeros((64, 64), dtype=np.uint8)
    creep[14, 26] = 1
    current = replace(current, creep=creep)
    first = plan(planner, current)
    feedback = engine.allocate(current, first.proposals)
    second = plan(planner, current, feedback)
    feedback = engine.allocate(current, second.proposals)
    target = planner.mission.target
    current = replace(
        current, own_units=tuple(replace(u, position=target) for u in current.own_units)
    )
    for time in (1, 2, 3):
        current = replace(current, time=time)
        planned = plan(planner, current, feedback)
        assert planner.mission.phase is CreepPhase.WAIT
        assert all("escort" not in p.proposal_id for p in planned.proposals)
        feedback = engine.allocate(current, planned.proposals)


def test_cancellation_releases_requests_and_units_in_the_same_frame():
    planner, _, current, _, feedback = clearing()
    planned = plan(planner, replace(current, enemy_race=Race.Terran), feedback)
    assert planned.unit_requests == () and len(planned.proposals) == 1
    assert planner.views()[0].status is MissionStatus.CANCELLED
    assert planner.mission is None


def test_graceful_cancellation_withdraws_until_its_deadline():
    planner, _, current, planned, feedback = clearing()
    mission = planner.mission
    far = replace(
        current, own_units=tuple(replace(u, position=Point2((35, 18))) for u in current.own_units)
    )
    belief = AwarenessModel().infer(far)
    intent = StrategyModel().decide(far, belief)
    mission.lifecycle.request_cancel(CancelMode.GRACEFUL, "stop_cleaning", 0)
    assert mission.step(
        far, belief, intent, planned.anchor, MissionFeedback.of(feedback, mission.mission_id)
    )
    mission.step(
        replace(far, time=9),
        belief,
        intent,
        planned.anchor,
        MissionFeedback.of(feedback, mission.mission_id),
    )
    assert mission.lifecycle.status is MissionStatus.CANCELLED and mission.unit_requests == ()


def squad_bot():
    bot = FakeBot()
    bot.units = [
        FakeUnit(10, UnitTypeId.RAVEN, 30, 15, dps=0, flying=True),
        FakeUnit(1, UnitTypeId.MARINE, 29, 15),
        FakeUnit(2, UnitTypeId.MARINE, 30, 15),
        FakeUnit(11, UnitTypeId.MEDIVAC, 30, 16, dps=0, flying=True),
    ]
    return bot


def clean_proposal():
    return replace(
        proposal("creep", -0.5, command=Command.REMOVE_CREEP, target=Point2((32, 15))),
        fallback=Point2((18, 18)),
    )


def test_execution_shoots_only_revealed_tumors_and_moves_support_without_attack_move():
    bot = squad_bot()
    tumor = FakeUnit(
        90,
        UnitTypeId.CREEPTUMORBURROWED,
        32,
        15,
        dps=0,
        structure=True,
        burrowed=True,
        revealed=True,
    )
    bot.enemy_structures = [tumor]
    remove_creep.execute(bot, bot.units, clean_proposal())
    assert bot.units[1].commands == [(AbilityId.ATTACK, tumor)]
    assert bot.units[2].commands == [(AbilityId.ATTACK, tumor)]
    assert {b.unit.tag for b in bot.registered} == {10, 11}
    assert all(isinstance(b, PathUnitToTarget) and b.sense_danger for b in bot.registered)
    bot.registered.clear()
    for u in bot.units:
        u.commands.clear()
    tumor.is_revealed = False
    remove_creep.execute(bot, bot.units, clean_proposal())
    assert all(not u.commands for u in bot.units)


def test_local_danger_overrides_tumor_attacks_for_every_squad_member():
    bot = squad_bot()
    bot.enemy_units = [FakeUnit(99, UnitTypeId.ZERGLING, 32, 15)]
    bot.enemy_structures = [FakeUnit(90, UnitTypeId.CREEPTUMOR, 32, 15, dps=0, structure=True)]
    remove_creep.execute(bot, bot.units, clean_proposal())
    assert all(not u.commands for u in bot.units)
    assert len(bot.registered) == 4
    assert {b.target for b in bot.registered} == {Point2((18, 18))}


def test_current_allocation_preemption_does_not_send_the_raven_out_alone():
    planner, engine, current, planned, _ = clearing()
    attack = proposal("offense", 0.0, unit_types=frozenset({UnitTypeId.MARINE, UnitTypeId.MEDIVAC}))
    result = engine.allocate(current, (*planned.proposals, attack))
    bot = squad_bot()
    bot.units = [bot.units[0]]  # the combat operation commands the other units
    behaviors.command_units(bot, result)
    assert len(bot.registered) == 1 and bot.registered[0].target == planned.anchor


def test_queued_or_existing_raven_prevents_duplicate_training(monkeypatch):
    bot = FakeBot()
    bot.mediator.own_unit_counts[UnitTypeId.RAVEN] = 1
    monkeypatch.setattr(TechUp, "execute", lambda *args: pytest.fail("duplicate tech request"))
    monkeypatch.setattr(SpawnController, "execute", lambda *args: pytest.fail("duplicate Raven"))
    assert not buying.RequestedUnits((RAVEN,)).execute(bot, {}, bot.mediator)


def test_replacement_trains_one_raven_and_merges_duplicate_requests(monkeypatch):
    bot = FakeBot()
    port = Barracks(50, add_on=True)
    port.has_techlab = True
    bot.mediator.get_own_structures_dict[UnitTypeId.STARPORT] = [port]
    bot.tech_ready_for_unit = lambda kind: True
    bot.get_build_structures = lambda *args: [port]
    bot.can_afford = lambda kind: True
    bot.supply_left = 5
    called = []
    monkeypatch.setattr(SpawnController, "execute", lambda self, *args: called.append(self) or True)
    assert buying.RequestedUnits((RAVEN, replace(RAVEN, owner="intel"))).execute(
        bot, {}, bot.mediator
    )
    assert len(called) == 1 and called[0].maximum == 1


def test_a_requested_raven_gets_a_tech_lab_and_reserves_its_port():
    bot = FakeBot()
    bot.can_afford = lambda kind: True
    port = Barracks(50)
    bot.mediator.get_own_structures_dict[UnitTypeId.STARPORT] = [port]
    assert buying.requested_producers(bot, (RAVEN,)) == frozenset({50})
    assert buying.RequestedUnits((RAVEN,)).execute(bot, {}, bot.mediator)
    assert port.built == [UnitTypeId.STARPORTTECHLAB]
    port.built.clear()
    assert not buying.RequestedUnits((RAVEN,), ignored=frozenset({50}), allow_tech=False).execute(
        SimpleNamespace(tech_ready_for_unit=lambda kind: False), {}, bot.mediator
    )
    assert port.built == []


def test_reactor_only_production_adds_a_starport_without_replacing_reactors(monkeypatch):
    bot = FakeBot()
    port = Barracks(50, add_on=True)
    port.has_techlab = False
    bot.mediator.get_own_structures_dict[UnitTypeId.STARPORT] = [port]
    bot.structure_pending = lambda kind: 0
    bot.can_afford = lambda kind: True
    built = []
    monkeypatch.setattr(BuildStructure, "execute", lambda self, *args: built.append(self) or True)
    assert buying.RequestedUnits((RAVEN,)).execute(bot, {}, bot.mediator)
    assert built[0].structure_id is UnitTypeId.STARPORT and built[0].to_count == 2
    assert not port.built


def test_actual_ares_spawner_limits_the_fixed_request_even_with_many_idle_ports():
    counts = {}
    bot = ProductionBot(counts)
    bot.cost_dict[UnitTypeId.RAVEN] = Cost(100, 200)
    bot.calculate_supply_cost = lambda kind: 2.0
    bot.production = [bot._structure(i, UnitTypeId.STARPORT) for i in range(5)]
    for port in bot.production:
        port.has_techlab = port.has_add_on = port.is_ready = True
    bot.mediator.get_own_structures_dict[UnitTypeId.STARPORT] = bot.production
    assert buying.RequestedUnits((RAVEN,)).execute(bot, {}, bot.mediator)
    assert bot.trained == [UnitTypeId.RAVEN]
    counts[UnitTypeId.RAVEN] = 1
    assert not buying.RequestedUnits((RAVEN,)).execute(bot, {}, bot.mediator)
    assert bot.trained == [UnitTypeId.RAVEN]


def test_lifting_port_is_never_given_a_tech_lab_by_a_request(monkeypatch):
    bot = FakeBot()
    port = Barracks(50)
    bot.mediator.get_own_structures_dict[UnitTypeId.STARPORT] = [port]
    monkeypatch.setattr(TechUp, "execute", lambda *args: pytest.fail("ignored lifting port"))
    assert not buying.RequestedUnits((RAVEN,), ignored=frozenset({50})).execute(
        bot, {}, bot.mediator
    )
    assert port.built == []


def test_random_opening_keeps_its_first_port_and_puts_the_lab_on_the_second():
    bot = FakeBot()
    first, second = Barracks(50), Barracks(60)
    bot.can_afford = lambda kind: True
    bot.mediator.get_own_structures_dict[UnitTypeId.STARPORT] = [first]
    requested = buying.RequestedUnits((RAVEN,), preserve_opening=True)
    assert not requested.execute(bot, {}, bot.mediator)
    assert not first.built
    first.has_add_on = True
    bot.mediator.get_own_structures_dict[UnitTypeId.STARPORT] = [first, second]
    assert requested.execute(bot, {}, bot.mediator)
    assert not first.built and second.built == [UnitTypeId.STARPORTTECHLAB]


def test_cooldown_retreat_does_not_shoot_even_an_unguarded_tumor():
    bot = squad_bot()
    bot.enemy_structures = [FakeUnit(90, UnitTypeId.CREEPTUMOR, 32, 15, dps=0, structure=True)]
    remove_creep.execute(bot, bot.units, replace(clean_proposal(), inputs=(("clear", 0.0),)))
    assert all(not u.commands for u in bot.units)


def test_medivac_heals_only_its_granted_marines_while_clearing():
    bot = squad_bot()
    bot.units[1].health = 20
    remove_creep.execute(bot, bot.units, clean_proposal())
    assert bot.units[3].commands == [(AbilityId.MEDIVACHEAL_HEAL, bot.units[1])]


@pytest.mark.parametrize("style", [BIO, MECH])
def test_zerg_openings_buy_raven_at_the_first_starport_and_remain_parseable(style):
    builds = yaml.safe_load((Path(__file__).resolve().parents[1] / "terran_builds.yml").read_text())
    opening = economy.opening_for(style, Race.Zerg)
    steps = builds["Builds"][opening]["OpeningBuildOrder"]
    bot = FakeBot()
    bot.calculate_cost = lambda kind: Cost(100, 100)
    bot.supply_type = UnitTypeId.SUPPLYDEPOT
    bot.gas_type = UnitTypeId.REFINERY
    bot.base_townhall_type = UnitTypeId.COMMANDCENTER
    parsed = BuildOrderParser(bot).parse(steps)
    assert any(step.command is UnitTypeId.RAVEN for step in parsed)
    tokens = [step.split()[1] for step in steps]
    assert tokens.index("starport") < tokens.index("starporttechlab") < tokens.index("raven")
    if "medivac" in tokens:
        assert tokens.index("raven") < tokens.index("medivac")
    for token in tokens:
        assert token in {"supply", "gas", "orbital", "expand"} or (
            token.upper() in UnitTypeId.__members__ or token.upper() in UpgradeId.__members__
        )
    assert economy.opening_for(style, Race.Terran) == style.opening


def test_whole_frame_carries_the_demand_and_mission_to_economy_and_logs():
    bot, logger = squad_bot(), FakeLogger()
    bot.state.creep = SimpleNamespace(data_numpy=frame().creep)
    bot.state.visibility.data_numpy[:] = 2
    bot.enemy_structures = [
        FakeUnit(
            90,
            UnitTypeId.CREEPTUMORBURROWED,
            32,
            15,
            dps=0,
            structure=True,
            burrowed=True,
            revealed=True,
        )
    ]
    layers = Layers(map_view=CREEP_MAP, logs=Logs(logger))
    result = play_frame(bot, 0, layers)
    assert any(view.kind == "remove_creep" for view in result.missions)
    assert result.economy.unit_requests == (RAVEN,)
    assert result.intel.detection.scan is None
    logged = logger.named("planner.economy_planned")[0]["data"]["unit_requests"]
    assert logged[0]["type"] == "RAVEN" and logged[0]["count"] == 1
    macro = next(b for b in bot.registered if isinstance(b, MacroPlan))
    assert any(isinstance(b, buying.RequestedUnits) for b in macro.macros)

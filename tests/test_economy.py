"""After the opening: upgrades, Orbital Commands, MULEs and production."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from types import SimpleNamespace

import pytest
from ares.behaviors.macro import (
    AutoSupply,
    BuildStructure,
    BuildWorkers,
    ExpansionController,
    GasBuildingController,
    MacroPlan,
    Mining,
    ProductionController,
    SpawnController,
    UpgradeCCs,
    UpgradeController,
)
from sc2.data import Race
from sc2.game_data import Cost
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from bot.attention import BaseView
from bot.attention.map import MapView
from bot.awareness import AwarenessModel
from bot.body.behaviors import economy as economy_behavior
from bot.ego.planners import economy
from bot.ego.strategy import Objective, StrategyModel

from .fakes import MAIN, MAP, FakeBot, FakeUnit, attention


def planned(*, opening_done: bool = True, objective: Objective = Objective.BUILD_ADVANTAGE, **kw):
    frame = attention(time=400.0, opening_done=opening_done, **kw)
    strategy = StrategyModel().decide(frame, AwarenessModel().infer(frame))
    return economy.plan(frame, replace(strategy, objective=objective))


def test_after_the_opening_the_plan_researches_upgrades_and_runs_orbitals() -> None:
    plan = planned()

    assert plan.upgrades == economy.styles.BIO.upgrades
    assert plan.upgrades[:3] == (
        UpgradeId.STIMPACK,
        UpgradeId.SHIELDWALL,
        UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,
    )
    assert (plan.orbitals, plan.mules) == (True, True)


def test_stabilizing_spends_on_the_army_not_on_upgrades() -> None:
    plan = planned(objective=Objective.STABILIZE)

    assert plan.upgrades == ()
    assert (plan.orbitals, plan.mules, plan.freeflow) == (True, True, True)


def test_the_opening_keeps_every_resource_to_the_build_runner() -> None:
    plan = planned(opening_done=False)

    assert (plan.active, plan.upgrades, plan.orbitals, plan.mules) == (False, (), False, False)


def test_the_upgrades_the_game_reports_done_are_counted() -> None:
    frame = replace(
        attention(time=400.0),
        upgrades=frozenset({UpgradeId.STIMPACK, UpgradeId.SHIELDWALL, UpgradeId.BANSHEECLOAK}),
    )
    strategy = StrategyModel().decide(frame, AwarenessModel().infer(frame))

    assert dict(economy.plan(frame, strategy).inputs)["upgrades_done"] == 2.0


def test_what_must_not_wait_for_the_army_runs_before_the_spawn_controller() -> None:
    # Ares' MacroPlan stops at the first behavior that acts, and the
    # SpawnController acts whenever production is idle: with upgrades after
    # it, traces 483722e and 3769f04 banked 5,400-5,600 gas and researched
    # nothing after the opening.
    bot = FakeBot()

    economy_behavior.execute(bot, planned())

    mining, macro = bot.registered
    assert isinstance(mining, Mining) and isinstance(macro, MacroPlan)
    assert [type(item) for item in macro.macros] == [
        AutoSupply,
        UpgradeCCs,
        BuildWorkers,
        GasBuildingController,
        economy_behavior.ExactResearch,
        UpgradeController,
        SpawnController,
        ProductionController,
    ]
    assert macro.macros[4].upgrades == economy.styles.BIO.upgrades
    upgrades = macro.macros[5]
    assert upgrades.upgrade_list == list(economy.styles.BIO.upgrades)
    assert not upgrades.prioritize
    assert macro.macros[1].to is UnitTypeId.ORBITALCOMMAND

    bot = FakeBot()
    economy_behavior.execute(bot, planned(objective=Objective.STABILIZE))
    (macro,) = [item for item in bot.registered if isinstance(item, MacroPlan)]
    assert not any(isinstance(item, UpgradeController) for item in macro.macros)


class Lab:
    """An idle Barracks Tech Lab that can research what it is asked."""

    def __init__(self) -> None:
        self.tag = 1
        self.type_id = UnitTypeId.BARRACKSTECHLAB
        self.is_ready = True
        self.is_idle = True
        self.abilities = {
            AbilityId.BARRACKSTECHLABRESEARCH_STIMPACK,
            AbilityId.RESEARCH_COMBATSHIELD,
        }
        self.researched: list[UpgradeId] = []

    def research(self, upgrade: UpgradeId) -> None:
        self.researched.append(upgrade)


class ResearchBot:
    """The AresBot surface Ares' UpgradeController reads."""

    def __init__(self, done: set[UpgradeId], lab: Lab) -> None:
        self.race = Race.Terran
        self.time_formatted = "06:40"
        self._done = done
        self.mediator = SimpleNamespace(
            get_own_structures_dict=defaultdict(list, {UnitTypeId.BARRACKSTECHLAB: [lab]})
        )

    def pending_or_complete_upgrade(self, upgrade: UpgradeId) -> bool:
        return upgrade in self._done

    def can_afford(self, upgrade: UpgradeId) -> bool:
        return True


def test_the_upgrade_controller_researches_the_first_upgrade_not_yet_done() -> None:
    lab = Lab()
    bot = ResearchBot({UpgradeId.STIMPACK}, lab)
    controller = UpgradeController(list(economy.styles.BIO.upgrades), base_location=None)

    acted = controller.execute(bot, {}, bot.mediator)

    # It acted, so the MacroPlan does not reach the SpawnController this frame.
    assert acted
    assert lab.researched == [UpgradeId.SHIELDWALL]


def mining_bot(*, energy: float) -> tuple[FakeBot, FakeUnit, list[FakeUnit]]:
    bot = FakeBot()
    orbital = FakeUnit(
        1, UnitTypeId.ORBITALCOMMAND, 10.5, 10.5, dps=0.0, structure=True, energy=energy
    )
    unfinished = FakeUnit(
        2, UnitTypeId.ORBITALCOMMAND, 30.5, 12.5, dps=0.0, structure=True, energy=200, ready=False
    )
    bot.structures = [orbital, unfinished]
    bot.townhalls = [orbital, unfinished]
    fields = [
        FakeUnit(10, UnitTypeId.MINERALFIELD, 17, 10, dps=0.0, minerals=900),
        FakeUnit(11, UnitTypeId.MINERALFIELD750, 17, 12, dps=0.0, minerals=1500),
        FakeUnit(12, UnitTypeId.MINERALFIELD, 17, 14, dps=0.0, minerals=1500),
        # The fullest, but by the unfinished Orbital only.
        FakeUnit(13, UnitTypeId.MINERALFIELD, 34, 12, dps=0.0, minerals=1800),
    ]
    bot.mineral_field = fields
    return bot, orbital, fields


def test_an_orbital_with_a_mules_energy_drops_it_on_the_fullest_mined_field() -> None:
    bot, orbital, fields = mining_bot(energy=50.0)

    economy_behavior.execute(bot, planned())

    assert orbital.commands == [(AbilityId.CALLDOWNMULE_CALLDOWNMULE, fields[1])]
    assert bot.structures[1].commands == []


def test_no_mule_below_its_energy_or_when_the_plan_says_no() -> None:
    bot, orbital, _ = mining_bot(energy=49.9)
    economy_behavior.execute(bot, planned())
    assert orbital.commands == []

    bot, orbital, _ = mining_bot(energy=200.0)
    economy_behavior.execute(bot, planned(opening_done=False))
    assert orbital.commands == []


def test_production_is_not_added_in_a_frame_the_spawn_controller_acts(monkeypatch) -> None:
    # Run on its own after the SpawnController (`bench/7/002`), Ares'
    # ProductionController ordered Tech Labs on Barracks the SpawnController
    # had just ordered to train, and the last order wins.
    calls: list[str] = []

    def recorder(name: str, acts: bool):
        def execute(self, ai, config, mediator) -> bool:
            calls.append(name)
            return acts

        return execute

    for behavior in (AutoSupply, UpgradeCCs, BuildWorkers, GasBuildingController):
        monkeypatch.setattr(behavior, "execute", recorder(behavior.__name__, False))
    monkeypatch.setattr(
        economy_behavior.ExactResearch, "execute", recorder("ExactResearch", False)
    )
    monkeypatch.setattr(UpgradeController, "execute", recorder("UpgradeController", False))
    monkeypatch.setattr(SpawnController, "execute", recorder("SpawnController", True))
    monkeypatch.setattr(ProductionController, "execute", recorder("ProductionController", True))
    bot = FakeBot()

    economy_behavior.execute(bot, planned())
    for behavior in bot.registered[1:]:
        behavior.execute(bot, {}, bot.mediator)

    assert calls[-1] == "SpawnController"
    assert "ProductionController" not in calls


def test_the_spawn_controller_leaves_alone_the_structure_that_took_an_add_on() -> None:
    # The last order wins (`bench/7/002`): a training order after the add-on
    # would cancel it. Add-ons run before the MacroPlan, outside it, because
    # inside it they came after a SpawnController that almost always acted
    # (`bench/ci-mech/000`: 9 of 13 Factories bare at 502 s).
    bare = Barracks(5)
    bot = add_on_bot([Barracks(1, add_on=True), bare])

    economy_behavior.execute(bot, planned())

    (macro,) = [item for item in bot.registered if isinstance(item, MacroPlan)]
    (spawn,) = [item for item in macro.macros if isinstance(item, SpawnController)]
    assert bare.built == [UnitTypeId.BARRACKSREACTOR]
    assert spawn.ignored_build_from_tags == {5}

    bot = add_on_bot([Barracks(1, add_on=True), Barracks(6)])
    economy_behavior.execute(bot, planned(objective=Objective.STABILIZE))
    (macro,) = [item for item in bot.registered if isinstance(item, MacroPlan)]
    (spawn,) = [item for item in macro.macros if isinstance(item, SpawnController)]
    # Stabilizing spends on the army, not on add-ons.
    assert spawn.ignored_build_from_tags == set()


def opening_plan(defense: float, objective: Objective = Objective.STABILIZE):
    frame = attention(time=150.0, opening_done=False)
    strategy = StrategyModel().decide(frame, AwarenessModel().infer(frame))
    return economy.plan(frame, replace(strategy, objective=objective, defense=defense))


def test_an_emergency_interrupts_the_opening_and_the_plan_takes_over() -> None:
    plan = opening_plan(economy.investment.OPENING_ABORT_DANGER)

    assert (plan.active, plan.interrupt_opening, plan.reason) == (
        True,
        True,
        "opening_interrupted",
    )
    # Stabilizing: everything to the army.
    assert plan.freeflow and plan.upgrades == ()
    assert (plan.orbitals, plan.mules) == (True, True)
    assert dict(plan.inputs)["danger"] == economy.investment.OPENING_ABORT_DANGER


@pytest.mark.parametrize(
    "defense, objective",
    [
        (economy.investment.OPENING_ABORT_DANGER - 0.01, Objective.STABILIZE),
        # A threat the strategy does not stabilize against yet.
        (0.9, Objective.BUILD_ADVANTAGE),
    ],
)
def test_the_opening_runs_on_below_the_emergency(defense, objective) -> None:
    plan = opening_plan(defense, objective)

    assert (plan.active, plan.interrupt_opening, plan.reason) == (False, False, "opening_runs")


class Runner:
    def __init__(self, completed: bool) -> None:
        self.build_completed = completed
        self.stopped = 0

    def set_build_completed(self) -> None:
        self.stopped += 1
        self.build_completed = True


def test_the_body_stops_the_build_runner_once_and_runs_the_plan_that_frame() -> None:
    bot = FakeBot()
    bot.build_order_runner = Runner(completed=False)
    plan = opening_plan(0.8)

    economy_behavior.execute(bot, plan)
    economy_behavior.execute(bot, plan)

    assert bot.build_order_runner.stopped == 1
    assert any(isinstance(behavior, MacroPlan) for behavior in bot.registered)

    bot = FakeBot()
    bot.build_order_runner = Runner(completed=False)
    economy_behavior.execute(bot, opening_plan(0.1))
    assert bot.build_order_runner.stopped == 0


def bases(count: int) -> tuple[BaseView, ...]:
    return (MAIN,) + tuple(
        BaseView(
            base_id=f"base:{20 + 8 * i}:40", position=Point2((20.5 + 8 * i, 40.5)), is_main=False
        )
        for i in range(count - 1)
    )


@pytest.mark.parametrize("count, ceiling", [(1, 4), (3, 12), (6, 24)])
def test_the_production_ceiling_grows_with_the_bases(count: int, ceiling: int) -> None:
    plan = planned(bases=bases(count), workers=16 * count)

    assert plan.max_production == ceiling
    assert dict(plan.inputs)["production_per_base"] == economy.investment.PRODUCTION_PER_BASE


class Producer:
    """A ready production structure, busy training."""

    def __init__(self, tag: int, type_id: UnitTypeId) -> None:
        self.tag = tag
        self.type_id = type_id
        self.is_ready = True
        self.is_idle = False
        self.orders = [SimpleNamespace(progress=0.1)]
        self.build_progress = 1.0


class IncomeBot:
    """The AresBot surface Ares' ProductionController reads: a six-base
    income, a bank, every Barracks busy and the army short of Marines."""

    _COSTS = {
        UnitTypeId.MARINE: Cost(50, 0),
        UnitTypeId.MARAUDER: Cost(100, 25),
        UnitTypeId.SIEGETANK: Cost(150, 125),
        UnitTypeId.MEDIVAC: Cost(100, 100),
    }

    def __init__(self, barracks: int, others: int) -> None:
        self.race = Race.Terran
        self.time_formatted = "12:53"
        self.minerals = 9930
        self.vespene = 3041
        self.config = {}
        self.start_location = Point2((10.5, 10.5))
        self.state = SimpleNamespace(
            score=SimpleNamespace(collection_rate_minerals=4000, collection_rate_vespene=1500)
        )
        structures = defaultdict(list)
        structures[UnitTypeId.BARRACKS] = [
            Producer(tag, UnitTypeId.BARRACKS) for tag in range(barracks)
        ]
        # Factories and Starports at the ceiling too: only Barracks are in question.
        structures[UnitTypeId.FACTORY] = [
            Producer(100 + tag, UnitTypeId.FACTORY) for tag in range(others)
        ]
        structures[UnitTypeId.STARPORT] = [
            Producer(200 + tag, UnitTypeId.STARPORT) for tag in range(others)
        ]
        counts = {
            UnitTypeId.MARINE: 15,
            UnitTypeId.MARAUDER: 13,
            UnitTypeId.SIEGETANK: 11,
            UnitTypeId.MEDIVAC: 9,
        }
        self.mediator = SimpleNamespace(
            get_own_structures_dict=structures,
            get_flying_structure_tracker={},
            get_own_unit_count=lambda *, unit_type_id: counts.get(unit_type_id, 0),
        )
        self.registered: list = []
        self.townhalls: list = []
        self.mineral_field: list = []
        self.structures: list = []

    def register_behavior(self, behavior) -> None:
        self.registered.append(behavior)

    def tech_requirement_progress(self, structure_type: UnitTypeId) -> float:
        return 1.0

    def not_started_but_in_building_tracker(self, structure_type: UnitTypeId) -> bool:
        return False

    def structure_pending(self, structure_type: UnitTypeId) -> int:
        return 0

    def calculate_cost(self, unit_type: UnitTypeId) -> Cost:
        return self._COSTS[unit_type]


def production_after(monkeypatch, count: int, barracks: int = 12) -> list[UnitTypeId]:
    built: list[UnitTypeId] = []

    def build(self, ai, config, mediator) -> bool:
        built.append(self.structure_id)
        return True

    monkeypatch.setattr(BuildStructure, "execute", build)
    # The tech is there; TechUp would only add Tech Labs.
    monkeypatch.setattr(
        "ares.behaviors.macro.production_controller.TechUp.execute",
        lambda self, ai, config, mediator: False,
    )
    ceiling = economy.investment.PRODUCTION_PER_BASE * count
    bot = IncomeBot(barracks, others=max(ceiling, 12))
    economy_behavior.execute(bot, planned(bases=bases(count), workers=16 * count))
    (macro,) = [item for item in bot.registered if isinstance(item, MacroPlan)]
    (production,) = [item for item in macro.macros if isinstance(item, ProductionController)]
    assert production.max_production_structures == ceiling
    production.execute(bot, {}, bot.mediator)
    return built


def test_six_bases_add_barracks_past_ares_default_ceiling(monkeypatch) -> None:
    # bench/7b: all three games reached 12 Barracks by 605-641 s. In 001
    # (Terran), with six bases, the bank then grew from 4,155 minerals at
    # 608.9 s to 9,930 at 773.1 s while the army fell to 31 units with 37
    # supply free: Ares stops adding production at 12 of a type.
    assert production_after(monkeypatch, count=6) == [UnitTypeId.BARRACKS]


def test_three_bases_keep_ares_default_ceiling(monkeypatch) -> None:
    assert production_after(monkeypatch, count=3) == []
    # The ceiling is a ceiling: below it, Ares' income rule still decides.
    assert production_after(monkeypatch, count=3, barracks=11) == [UnitTypeId.BARRACKS]


def test_the_six_base_ceiling_holds_at_its_count(monkeypatch) -> None:
    assert production_after(monkeypatch, count=6, barracks=24) == []


class Barracks:
    """A Barracks the way Ares' macro behaviors read one: ready or not, idle or
    training, with an add-on or without."""

    def __init__(self, tag: int, *, idle: bool = True, add_on: bool = False, ready: bool = True):
        self.tag = tag
        self.type_id = UnitTypeId.BARRACKS
        self.is_ready = ready
        self.is_idle = idle
        self.has_add_on = add_on
        self.build_progress = 1.0 if ready else 0.5
        self.orders: list = []
        self.built: list[UnitTypeId] = []

    def build(self, unit_type: UnitTypeId) -> None:
        self.built.append(unit_type)


def add_on_bot(
    barracks: list[Barracks],
    *,
    reactors: int = 0,
    minerals: int = 9930,
    vespene: int = 3041,
) -> FakeBot:
    bot = FakeBot()
    bot.minerals = minerals
    bot.vespene = vespene
    bot.mediator.get_own_structures_dict[UnitTypeId.BARRACKS] = list(barracks)
    bot.mediator.get_own_structures_dict[UnitTypeId.BARRACKSREACTOR] = [
        object() for _ in range(reactors)
    ]
    return bot


def add_ons_ordered(barracks: list[Barracks], *, share: float = 1.0, **kw) -> list:
    bot = add_on_bot(barracks, **kw)

    tag = economy_behavior.add_add_on(bot, UnitTypeId.BARRACKS, share)

    ordered = [(item.tag, item.built[0]) for item in barracks if item.built]
    assert tag == (ordered[0][0] if ordered else None)
    return ordered


def test_the_plan_adds_add_ons_after_the_opening_by_the_mix() -> None:
    plan = planned()

    assert plan.addons and plan.addons_on is UnitTypeId.BARRACKS
    # Marines (0.55) on Reactors, Marauders (0.2) on Tech Labs.
    assert plan.reactor_share == pytest.approx(0.55 / (0.55 + 2 * 0.2))
    assert not planned(opening_done=False).addons
    assert not planned(objective=Objective.STABILIZE).addons


def test_a_barracks_with_no_add_on_gets_one_lowest_tag_first() -> None:
    # bench/7b/001: 5 of the 12 Barracks had no add-on at 773 s, while the bank
    # grew to 9,930 minerals with 37 supply free and the army fell to 31 units.
    with_add_on = [Barracks(tag, add_on=True) for tag in range(7)]
    without = [Barracks(tag, add_on=False) for tag in range(7, 12)]

    assert add_ons_ordered(with_add_on + without) == [(7, UnitTypeId.BARRACKSREACTOR)]


def test_only_a_ready_and_idle_barracks_takes_an_add_on() -> None:
    # An add-on order replaces the order a training Barracks already has.
    assert add_ons_ordered(
        [
            Barracks(1, idle=False),
            Barracks(2, ready=False),
            Barracks(3, add_on=True),
            Barracks(4),
            Barracks(5),
        ]
    ) == [(4, UnitTypeId.BARRACKSREACTOR)]
    assert add_ons_ordered([]) == []


def test_past_the_reactor_share_the_add_on_is_a_tech_lab() -> None:
    # Four Barracks, one with a Reactor: a second Reactor would be half.
    barracks = [Barracks(1, add_on=True), Barracks(2), Barracks(3), Barracks(4)]

    assert add_ons_ordered(barracks, share=0.5, reactors=1) == [
        (2, UnitTypeId.BARRACKSREACTOR)
    ]
    barracks = [Barracks(1, add_on=True), Barracks(2), Barracks(3), Barracks(4)]
    assert add_ons_ordered(barracks, share=0.4, reactors=1) == [
        (2, UnitTypeId.BARRACKSTECHLAB)
    ]


def test_no_add_on_the_bot_cannot_pay_for() -> None:
    def barracks():
        return [Barracks(tag) for tag in range(3)]

    assert add_ons_ordered(barracks(), minerals=50, vespene=49) == []
    assert add_ons_ordered(barracks(), minerals=49, vespene=50) == []
    assert add_ons_ordered(barracks(), minerals=50, vespene=50) == [
        (0, UnitTypeId.BARRACKSREACTOR)
    ]
    # A Tech Lab costs 50/25.
    assert add_ons_ordered(barracks(), share=0.0, minerals=50, vespene=25) == [
        (0, UnitTypeId.BARRACKSTECHLAB)
    ]


class Geyser:
    """A vespene geyser, or the Refinery standing on one."""

    def __init__(self, tag: int, position: Point2) -> None:
        self.tag = tag
        self.type_id = UnitTypeId.VESPENEGEYSER
        self.position = position
        self.build_progress = 1.0


class GasBot:
    """The AresBot surface Ares' GasBuildingController reads: six bases, two
    geysers each, and a Refinery already on the first `refineries` of them."""

    def __init__(self, refineries: int) -> None:
        self.race = Race.Terran
        self.gas_type = UnitTypeId.REFINERY
        self.minerals = 4000
        self.vespene = 88
        self.config = {}
        self.start_location = Point2((10.5, 10.5))
        self.townhalls = [
            Geyser(tag, Point2((10.5 + 20.0 * tag, 10.5))) for tag in range(6)
        ]
        self.vespene_geyser = [
            Geyser(100 + index, Point2((8.5 + 20.0 * (index // 2), 14.5 + 6.0 * (index % 2))))
            for index in range(12)
        ]
        self.gas_buildings = self.vespene_geyser[:refineries]
        self.all_gas_buildings = self.gas_buildings
        self.mediator = SimpleNamespace(
            get_building_counter=defaultdict(int),
            select_worker=lambda **kwargs: SimpleNamespace(tag=7),
            build_with_specific_worker=self._build,
        )
        self.built: list[Point2] = []

    def _build(self, *, worker, structure_type, pos) -> None:
        self.built.append(pos.tag)

    def not_started_but_in_building_tracker(self, structure_type: UnitTypeId) -> int:
        return 0


def test_the_gas_target_takes_every_geyser_the_workers_can_man() -> None:
    # bench/base3: the target stopped at seven Refineries from ~470 s on,
    # with six bases (twelve geysers) and 83 workers, while gas fell below
    # 100 with more than 800 minerals banked in 5-30 samples per game.
    plan = planned(bases=bases(6), workers=83)

    assert plan.gas == 11
    assert dict(plan.inputs)["gas_worker_share"] == economy.investment.GAS_WORKER_SHARE


@pytest.mark.parametrize(
    "count, workers, target",
    [
        # Never more geysers than the bases have.
        (3, 83, 6),
        # Never more Refineries than the share of workers can mine.
        (6, 12, 1),
        (6, 41, 5),
    ],
)
def test_the_gas_target_stays_within_the_geysers_and_the_workers(
    count: int, workers: int, target: int
) -> None:
    assert planned(bases=bases(count), workers=workers).gas == target


def test_six_bases_take_an_eighth_geyser_that_the_old_target_refused() -> None:
    bot = GasBot(refineries=7)

    assert not GasBuildingController(to_count=7).execute(bot, {}, bot.mediator)
    assert bot.built == []

    plan = planned(bases=bases(6), workers=83)
    GasBuildingController(to_count=plan.gas).execute(bot, {}, bot.mediator)

    # The nearest geyser with no Refinery on it, of the five still free.
    assert bot.built == [bot.vespene_geyser[7].tag]


def map_with(sites: int) -> MapView:
    """The test map, but with `sites` places to put a townhall."""

    return replace(
        MAP,
        expansions=tuple(Point2((10.5 + 8.0 * index, 40.5)) for index in range(sites)),
    )


def test_the_sixth_base_is_not_the_last() -> None:
    # bench/base3: every one of the nine games asked for its last base at
    # 494-570 s and then held six for the 205-693 s that were left, banking
    # 7,585-18,850 minerals. With six bases the old test wanted 96 workers and
    # the plan builds at most MAX_WORKERS, so it could never be met again.
    assert economy.investment.MINERAL_WORKERS_PER_BASE * 6 > economy.investment.MAX_WORKERS

    plan = planned(bases=bases(6), workers=83, map_view=map_with(9))

    assert (plan.expand, plan.bases) == (True, 7)
    assert plan.reason == "worker_cap_reached"
    assert dict(plan.inputs)["saturated_at"] == float(economy.investment.MAX_WORKERS)


def test_the_target_stops_at_the_bases_the_map_offers() -> None:
    plan = planned(bases=bases(4), workers=83, map_view=map_with(4))

    assert (plan.expand, plan.bases) == (False, 4)
    assert plan.reason == "no_expansion_left"
    assert dict(plan.inputs)["expansion_sites"] == 4.0


@pytest.mark.parametrize(
    "count, workers, expand, reason",
    [
        # Below the cap the mineral lines still decide, as before.
        (3, 47, False, "build_economy"),
        (3, 48, True, "mineral_lines_saturated"),
        (5, 79, False, "build_economy"),
        (5, 80, True, "mineral_lines_saturated"),
    ],
)
def test_below_the_worker_cap_the_mineral_lines_still_decide(
    count: int, workers: int, expand: bool, reason: str
) -> None:
    plan = planned(bases=bases(count), workers=workers, map_view=map_with(9))

    assert (plan.expand, plan.reason) == (expand, reason)


class ExpansionBot:
    """The AresBot surface Ares' ExpansionController reads: `held` ready
    townhalls and free expansion sites beyond them."""

    def __init__(self, held: int, sites: int) -> None:
        self.minerals = 4000
        self.vespene = 500
        self.base_townhall_type = UnitTypeId.COMMANDCENTER
        self.sites = [Point2((10.5 + 8.0 * index, 40.5)) for index in range(sites)]
        self.townhalls = [
            SimpleNamespace(tag=index, is_ready=True, position=self.sites[index])
            for index in range(held)
        ]
        self.built: list[Point2] = []
        self.mediator = SimpleNamespace(
            get_ground_grid=None,
            get_own_expansions=[(site, 0.0) for site in self.sites[held:]],
            is_position_safe=lambda **kwargs: True,
            can_place_structure=lambda **kwargs: True,
            select_worker=lambda **kwargs: SimpleNamespace(tag=7),
            build_with_specific_worker=self._build,
        )

    def _build(self, *, worker, structure_type, pos) -> None:
        self.built.append(pos)

    def structure_pending(self, structure_type: UnitTypeId) -> int:
        return 0

    def can_afford(self, item) -> bool:
        return True

    def location_is_blocked(self, mediator, location) -> bool:
        return False


def test_six_bases_take_a_seventh_that_the_old_target_refused() -> None:
    bot = ExpansionBot(held=6, sites=9)

    # What the old plan asked for with six bases and 83 workers: no expansion.
    assert not ExpansionController(to_count=6).execute(bot, {}, bot.mediator)
    assert bot.built == []

    plan = planned(bases=bases(6), workers=83, map_view=map_with(9))
    ExpansionController(to_count=plan.bases).execute(bot, {}, bot.mediator)

    assert bot.built == [bot.sites[6]]


class Armory:
    """A ready Armory, idle or researching by ability."""

    def __init__(self, tag: int, *, researching: AbilityId | None = None) -> None:
        self.tag = tag
        self.is_ready = True
        self.is_idle = researching is None
        order = SimpleNamespace(ability=SimpleNamespace(exact_id=researching))
        self.orders = [] if researching is None else [order]
        self.abilities = {
            AbilityId.ARMORYRESEARCH_TERRANVEHICLEWEAPONSLEVEL1,
            AbilityId.ARMORYRESEARCH_TERRANVEHICLEANDSHIPPLATINGLEVEL1,
        }
        self.ordered: list[AbilityId] = []

    def __call__(self, ability: AbilityId) -> None:
        self.ordered.append(ability)


def research_bot(armories: list[Armory], *, game_ability: AbilityId) -> FakeBot:
    """The game's data names `game_ability` for the plating, and the table of
    python-sc2 the plating's own ability."""

    bot = FakeBot()
    bot.minerals, bot.vespene = 1000, 1000
    bot.state = SimpleNamespace(upgrades=set())
    own = {
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL1: AbilityId.ARMORYRESEARCH_TERRANVEHICLEWEAPONSLEVEL1,
        UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1: game_ability,
    }
    bot.game_data = SimpleNamespace(
        upgrades={
            upgrade.value: SimpleNamespace(research_ability=SimpleNamespace(exact_id=ability))
            for upgrade, ability in own.items()
        }
    )
    bot.can_afford = lambda item: True
    bot.mediator.get_own_structures_dict[UnitTypeId.ARMORY] = armories
    return bot


PLATING = (UpgradeId.TERRANVEHICLEWEAPONSLEVEL1, UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1)


def test_the_plating_is_ordered_by_the_ability_the_armory_offers() -> None:
    armory = Armory(1)
    bot = research_bot([armory], game_ability=AbilityId.RESEARCH_TERRANVEHICLEANDSHIPPLATING)
    bot.state.upgrades = {UpgradeId.TERRANVEHICLEWEAPONSLEVEL1}

    assert economy_behavior.ExactResearch(PLATING).execute(bot, {}, bot.mediator)
    assert armory.ordered == [AbilityId.ARMORYRESEARCH_TERRANVEHICLEANDSHIPPLATINGLEVEL1]


def test_exact_research_keeps_the_order_and_yields_to_ares_first() -> None:
    # The weapons come first and resolve the same way both ways: they are the
    # UpgradeController's, and the only Armory is theirs (`bench/smoke-mech2`).
    armory = Armory(1)
    bot = research_bot([armory], game_ability=AbilityId.RESEARCH_TERRANVEHICLEANDSHIPPLATING)

    assert not economy_behavior.ExactResearch(PLATING).execute(bot, {}, bot.mediator)
    assert armory.ordered == []

    # With the weapons underway on one Armory, the plating takes the other.
    busy = Armory(1, researching=AbilityId.ARMORYRESEARCH_TERRANVEHICLEWEAPONSLEVEL1)
    free = Armory(2)
    bot = research_bot(
        [busy, free], game_ability=AbilityId.RESEARCH_TERRANVEHICLEANDSHIPPLATING
    )
    assert economy_behavior.ExactResearch(PLATING).execute(bot, {}, bot.mediator)
    assert free.ordered == [AbilityId.ARMORYRESEARCH_TERRANVEHICLEANDSHIPPLATINGLEVEL1]


def test_exact_research_leaves_alone_what_resolves_and_what_is_underway() -> None:
    fine = Armory(1)
    bot = research_bot(
        [fine], game_ability=AbilityId.ARMORYRESEARCH_TERRANVEHICLEANDSHIPPLATINGLEVEL1
    )
    assert not economy_behavior.ExactResearch(PLATING).execute(bot, {}, bot.mediator)

    busy, idle = (
        Armory(1, researching=AbilityId.ARMORYRESEARCH_TERRANVEHICLEANDSHIPPLATINGLEVEL1),
        Armory(2),
    )
    bot = research_bot(
        [busy, idle], game_ability=AbilityId.RESEARCH_TERRANVEHICLEANDSHIPPLATING
    )
    assert not economy_behavior.ExactResearch(PLATING).execute(bot, {}, bot.mediator)
    assert idle.ordered == []

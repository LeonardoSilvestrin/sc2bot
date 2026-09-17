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
from bot.awareness import AwarenessModel
from bot.body.behaviors import economy as economy_behavior
from bot.ego.planners import economy
from bot.ego.strategy import Objective, StrategyModel

from .fakes import MAIN, FakeBot, FakeUnit, attention


def planned(*, opening_done: bool = True, objective: Objective = Objective.BUILD_ADVANTAGE, **kw):
    frame = attention(time=400.0, opening_done=opening_done, **kw)
    strategy = StrategyModel().decide(frame, AwarenessModel().infer(frame))
    return economy.plan(frame, replace(strategy, objective=objective))


def test_after_the_opening_the_plan_researches_upgrades_and_runs_orbitals() -> None:
    plan = planned()

    assert plan.upgrades == economy.UPGRADES
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
        UpgradeController,
        SpawnController,
        ProductionController,
    ]
    upgrades = macro.macros[4]
    assert upgrades.upgrade_list == list(economy.UPGRADES)
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
    controller = UpgradeController(list(economy.UPGRADES), base_location=None)

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
    monkeypatch.setattr(UpgradeController, "execute", recorder("UpgradeController", False))
    monkeypatch.setattr(SpawnController, "execute", recorder("SpawnController", True))
    monkeypatch.setattr(ProductionController, "execute", recorder("ProductionController", True))
    bot = FakeBot()

    economy_behavior.execute(bot, planned())
    for behavior in bot.registered[1:]:
        behavior.execute(bot, {}, bot.mediator)

    assert calls[-1] == "SpawnController"
    assert "ProductionController" not in calls


def opening_plan(defense: float, objective: Objective = Objective.STABILIZE):
    frame = attention(time=150.0, opening_done=False)
    strategy = StrategyModel().decide(frame, AwarenessModel().infer(frame))
    return economy.plan(frame, replace(strategy, objective=objective, defense=defense))


def test_an_emergency_interrupts_the_opening_and_the_plan_takes_over() -> None:
    plan = opening_plan(economy.OPENING_ABORT_DANGER)

    assert (plan.active, plan.interrupt_opening, plan.reason) == (
        True,
        True,
        "opening_interrupted",
    )
    # Stabilizing: everything to the army.
    assert plan.freeflow and plan.upgrades == ()
    assert (plan.orbitals, plan.mules) == (True, True)
    assert dict(plan.inputs)["danger"] == economy.OPENING_ABORT_DANGER


@pytest.mark.parametrize(
    "defense, objective",
    [
        (economy.OPENING_ABORT_DANGER - 0.01, Objective.STABILIZE),
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
    assert dict(plan.inputs)["production_per_base"] == economy.PRODUCTION_PER_BASE


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
    ceiling = economy.PRODUCTION_PER_BASE * count
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

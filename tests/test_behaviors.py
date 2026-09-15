from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from types import SimpleNamespace

import pytest
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import AMove, PathUnitToTarget, SiegeTankDecision
from ares.behaviors.macro import ExpansionController, MacroPlan, Mining, SpawnController
from sc2.game_data import Cost
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.body import behaviors
from bot.body.behaviors import economy as economy_behavior
from bot.body.engine import Engine
from bot.ego.planners import Command, EconomyPlan, economy

from .fakes import FakeBot, FakeUnit, attention, proposal, unit


def maneuvers(bot) -> dict[int, list]:
    return {
        behavior.micros[-1].unit.tag: behavior.micros
        for behavior in bot.registered
        if isinstance(behavior, CombatManeuver)
    }


def test_commands_go_only_to_granted_units() -> None:
    bot = FakeBot()
    bot.units = [
        FakeUnit(1, UnitTypeId.MARINE, 30, 30),
        FakeUnit(2, UnitTypeId.SIEGETANK, 10, 10, dps=20, hit_points=175),
        FakeUnit(3, UnitTypeId.MARINE, 12, 12),
    ]
    frame = attention(
        own_units=(unit(1, x=30, y=30), unit(2, UnitTypeId.SIEGETANK, 10, 10), unit(3, x=12, y=12))
    )
    result = Engine().allocate(
        frame,
        (
            proposal("defense:main", 1.0, count=1),
            proposal("core_army", 0.0, command=Command.HOLD, target=Point2((20, 20))),
        ),
    )
    bot.units = bot.units[:2]  # unit 3 died before execution

    behaviors.command_units(bot, result)

    by_tag = maneuvers(bot)
    assert sorted(by_tag) == [1, 2]
    assert [type(micro) for micro in by_tag[1]] == [AMove]
    assert [type(micro) for micro in by_tag[2]] == [SiegeTankDecision, PathUnitToTarget]


def test_a_tank_stays_sieged_only_while_holding_and_a_holder_fights_what_comes() -> None:
    bot = FakeBot()
    tank = FakeUnit(2, UnitTypeId.SIEGETANK, 10, 10, dps=20, hit_points=175)
    marine = FakeUnit(1, UnitTypeId.MARINE, 30, 30)
    bot.enemy_units = [FakeUnit(90, UnitTypeId.ZERGLING, 32, 30, hit_points=35.0)]
    target = Point2((20, 20))

    behaviors.BY_COMMAND[Command.HOLD](
        bot, [tank, marine], proposal("core_army", 0.0, command=Command.HOLD, target=target)
    )
    held = maneuvers(bot)
    bot.registered = []
    behaviors.BY_COMMAND[Command.ATTACK](bot, [tank], proposal("defense:main", 1.0))
    attacking = maneuvers(bot)

    assert held[2][0].stay_sieged_near_target
    assert isinstance(held[2][1], PathUnitToTarget)
    assert [type(micro) for micro in held[1]] == [AMove]
    assert not attacking[2][0].stay_sieged_near_target
    assert isinstance(attacking[2][1], AMove)


def test_the_economy_runs_mining_always_and_macro_only_after_the_opening() -> None:
    plan = EconomyPlan(
        active=False,
        workers=22,
        gas=1,
        bases=1,
        expand=False,
        freeflow=False,
        composition=economy.COMPOSITION,
        reason="opening_runs",
    )
    bot = FakeBot()
    inactive = economy_behavior.execute(bot, plan)
    assert [type(behavior) for behavior in bot.registered] == [Mining]
    assert inactive == economy_behavior.SpawnMode(freeflow=False, reason="plan_inactive")

    bot = FakeBot()
    economy_behavior.execute(
        bot, replace(plan, active=True, workers=44, gas=2, bases=2, expand=True)
    )
    mining, macro = bot.registered
    assert isinstance(mining, Mining) and isinstance(macro, MacroPlan)
    assert any(isinstance(item, ExpansionController) for item in macro.macros)


# 11 Marines, 4 Marauders, 3 Siege Tanks and 2 Medivacs: every type exactly at
# its share of the composition.
EXACT = {
    UnitTypeId.MARINE: 11,
    UnitTypeId.MARAUDER: 4,
    UnitTypeId.SIEGETANK: 3,
    UnitTypeId.MEDIVAC: 2,
}
_COSTS = {
    UnitTypeId.MARINE: (Cost(50, 0), 1.0),
    UnitTypeId.MARAUDER: (Cost(100, 25), 2.0),
    UnitTypeId.SIEGETANK: (Cost(150, 125), 3.0),
    UnitTypeId.MEDIVAC: (Cost(100, 100), 2.0),
}


class ProductionStructure:
    """An idle production structure; SpawnController keys its orders by it."""

    def __init__(self, tag: int, type_id: UnitTypeId, trained: list[UnitTypeId]) -> None:
        self.tag = tag
        self.type_id = type_id
        self._trained = trained

    def train(self, unit_type: UnitTypeId) -> None:
        self._trained.append(unit_type)


class ProductionBot:
    """The AresBot surface Ares' SpawnController reads: idle Barracks, Factory
    and Starport, a bank, free supply and the army counts Ares keeps."""

    def __init__(self, counts: dict[UnitTypeId, int]) -> None:
        self.minerals = 5000
        self.vespene = 3000
        self.supply_left = 30.0
        self.num_larva_left = 0
        self.start_location = Point2((10.5, 10.5))
        self.state = SimpleNamespace(upgrades=set())
        self.registered: list = []
        self.trained: list[UnitTypeId] = []
        self.cost_dict = {unit_type: cost for unit_type, (cost, _) in _COSTS.items()}
        self.production = [
            self._structure(tag, type_id)
            for tag, type_id in enumerate(
                (UnitTypeId.BARRACKS, UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT)
            )
        ]
        self.mediator = SimpleNamespace(
            get_own_structures_dict=defaultdict(list),
            get_own_unit_count=lambda *, unit_type_id: counts.get(unit_type_id, 0),
            clear_role=lambda *, tag: None,
        )

    def _structure(self, tag: int, type_id: UnitTypeId) -> ProductionStructure:
        return ProductionStructure(tag, type_id, self.trained)

    def tech_ready_for_unit(self, unit_type: UnitTypeId) -> bool:
        return True

    def get_build_structures(self, structure_types, unit_type, build_dict=None, ignored=None):
        taken = {structure.tag for structure in (build_dict or {})}
        return [
            structure
            for structure in self.production
            if structure.type_id in structure_types and structure.tag not in taken
        ]

    def can_afford(self, unit_type: UnitTypeId) -> bool:
        cost = self.cost_dict[unit_type]
        return self.minerals >= cost.minerals and self.vespene >= cost.vespene

    def calculate_supply_cost(self, unit_type: UnitTypeId) -> float:
        return _COSTS[unit_type][1]

    def register_behavior(self, behavior) -> None:
        self.registered.append(behavior)


def active_plan(**changes) -> EconomyPlan:
    plan = EconomyPlan(
        active=True,
        workers=80,
        gas=7,
        bases=5,
        expand=False,
        freeflow=False,
        composition=economy.COMPOSITION,
        reason="build_economy",
    )
    return replace(plan, **changes)


def spawner(bot) -> SpawnController:
    (macro,) = [item for item in bot.registered if isinstance(item, MacroPlan)]
    (spawn,) = [item for item in macro.macros if isinstance(item, SpawnController)]
    return spawn


def test_an_army_exactly_at_its_composition_keeps_growing() -> None:
    # Traces 483722e (417.9-589.0 s, 11/4/3/2) and 3769f04 (481.5-573.5 s,
    # 22/8/6/4): with every type exactly at its share, Ares' SpawnController
    # skipped them all while 5,000 minerals piled up.
    composition = {
        unit_type: {"proportion": proportion, "priority": priority}
        for unit_type, proportion, priority in economy.COMPOSITION
    }
    stuck = ProductionBot(EXACT)
    assert not SpawnController(composition).execute(stuck, {}, stuck.mediator)
    assert stuck.trained == []

    bot = ProductionBot(EXACT)
    mode = economy_behavior.execute(bot, active_plan())

    assert spawner(bot).execute(bot, {}, bot.mediator)
    assert UnitTypeId.SIEGETANK in bot.trained
    assert (mode.freeflow, mode.reason) == (True, "composition_met")
    assert dict(mode.counts) == EXACT


@pytest.mark.parametrize(
    "counts, freeflow, reason",
    [
        ({**EXACT, UnitTypeId.MARINE: 12}, False, "composition_short"),
        ({}, False, "composition_short"),
        ({**EXACT, UnitTypeId.MARINE: 12}, True, "plan_freeflow"),
    ],
)
def test_the_spawn_mode_follows_the_plan_unless_the_composition_is_met(
    counts: dict[UnitTypeId, int], freeflow: bool, reason: str
) -> None:
    bot = ProductionBot(counts)

    mode = economy_behavior.execute(bot, active_plan(freeflow=freeflow))

    assert (mode.freeflow, mode.reason) == (freeflow, reason)
    assert spawner(bot).freeflow_mode is freeflow

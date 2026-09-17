from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from types import SimpleNamespace

import pytest
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    AMove,
    PathUnitToTarget,
    SiegeTankDecision,
    UseAbility,
)
from ares.behaviors.macro import ExpansionController, MacroPlan, Mining, SpawnController
from sc2.game_data import Cost
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.body import behaviors
from bot.body.behaviors import attack
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


def test_a_retreat_walks_back_without_fighting_and_unsieges_tanks_first() -> None:
    bot = FakeBot()
    tank = FakeUnit(2, UnitTypeId.SIEGETANKSIEGED, 40, 40, dps=40, hit_points=175)
    marine = FakeUnit(1, UnitTypeId.MARINE, 41, 40)
    medivac = FakeUnit(3, UnitTypeId.MEDIVAC, 40, 41, dps=0.0, flying=True)
    # An enemy right beside them does not stop the retreat.
    bot.enemy_units = [FakeUnit(90, UnitTypeId.ZERGLING, 42, 40, hit_points=35.0)]
    rally = Point2((18, 18))

    behaviors.BY_COMMAND[Command.RETREAT](
        bot,
        [tank, marine, medivac],
        proposal("offense", 0.0, command=Command.RETREAT, target=rally),
    )

    by_tag = maneuvers(bot)
    assert [type(micro) for micro in by_tag[1]] == [PathUnitToTarget]
    assert [type(micro) for micro in by_tag[2]] == [SiegeTankDecision, PathUnitToTarget]
    assert by_tag[2][0].force_unsiege
    assert by_tag[3][0].grid is bot.mediator.get_air_grid
    assert by_tag[1][0].grid is bot.mediator.get_ground_grid
    assert {micros[-1].target for micros in by_tag.values()} == {rally}
    assert not any(micros[-1].sense_danger for micros in by_tag.values())


STIM_MARINE = AbilityId.EFFECT_STIM_MARINE


def bio(tag, type_id=UnitTypeId.MARINE, x=30.0, y=30.0, **kw):
    ability = attack.STIMS[type_id][0] if type_id in attack.STIMS else None
    kw.setdefault("abilities", () if ability is None else (ability,))
    return FakeUnit(tag, type_id, x, y, **kw)


@pytest.mark.parametrize(
    "marine, enemy, stims",
    [
        # An enemy exactly at the stim range.
        (bio(1), FakeUnit(90, UnitTypeId.ZERGLING, 30 + attack.STIM_RANGE, 30), True),
        (bio(1), FakeUnit(90, UnitTypeId.ZERGLING, 30.5 + attack.STIM_RANGE, 30), False),
        # Already stimmed.
        (bio(1, buffs=(BuffId.STIMPACK,)), FakeUnit(90, UnitTypeId.ZERGLING, 32, 30), False),
        # Not researched, or on cooldown: the game does not offer it.
        (bio(1, abilities=()), FakeUnit(90, UnitTypeId.ZERGLING, 32, 30), False),
        # Exactly half its health, and just below.
        (bio(1, health=22.5), FakeUnit(90, UnitTypeId.ZERGLING, 32, 30), True),
        (bio(1, health=22.0), FakeUnit(90, UnitTypeId.ZERGLING, 32, 30), False),
        # A worker is no fight.
        (bio(1), FakeUnit(90, UnitTypeId.DRONE, 32, 30), False),
    ],
)
def test_bio_stims_only_near_a_fight_with_the_health_to_spare(marine, enemy, stims) -> None:
    bot = FakeBot()
    bot.enemy_units = [enemy]

    report = behaviors.BY_COMMAND[Command.ATTACK](bot, [marine], proposal("offense", 0.0))

    micros = maneuvers(bot)[1]
    if stims:
        assert [type(micro) for micro in micros] == [UseAbility, AMove]
        assert (micros[0].ability, micros[0].unit) == (STIM_MARINE, marine)
        assert report.stimmed == (1,)
    else:
        assert [type(micro) for micro in micros] == [AMove]
        assert report.stimmed == ()


def test_a_marauder_uses_its_own_stim() -> None:
    bot = FakeBot()
    marauder = bio(2, UnitTypeId.MARAUDER, hit_points=125.0)
    bot.enemy_units = [FakeUnit(90, UnitTypeId.ROACH, 33, 30)]

    behaviors.BY_COMMAND[Command.ATTACK](bot, [marauder], proposal("defense:x", 1.0))

    assert maneuvers(bot)[2][0].ability is AbilityId.EFFECT_STIM_MARAUDER


def test_a_medivac_follows_its_group_instead_of_flying_ahead() -> None:
    bot = FakeBot()
    marine = bio(1, x=30, y=30)
    marauder = bio(2, UnitTypeId.MARAUDER, x=34, y=30)
    medivac = FakeUnit(3, UnitTypeId.MEDIVAC, 50, 50, dps=0.0, flying=True)
    target = Point2((60, 60))

    report = behaviors.BY_COMMAND[Command.ATTACK](
        bot, [marine, marauder, medivac], proposal("offense", 0.0, target=target)
    )

    by_tag = maneuvers(bot)
    assert by_tag[3][-1].target == Point2((32, 30))
    assert {by_tag[1][-1].target, by_tag[2][-1].target} == {target}
    assert report.escorts == (3,)

    bot = FakeBot()
    alone = behaviors.BY_COMMAND[Command.ATTACK](
        bot, [medivac], proposal("offense", 0.0, target=target)
    )
    assert maneuvers(bot)[3][-1].target == target
    assert alone.escorts == ()


def test_every_grant_reports_its_reactions_once() -> None:
    bot = FakeBot()
    bot.units = [bio(1), bio(2, x=31), FakeUnit(3, UnitTypeId.MEDIVAC, 30, 31, dps=0.0)]
    bot.enemy_units = [FakeUnit(90, UnitTypeId.ZERGLING, 32, 30)]
    frame = attention(
        own_units=(unit(1, x=30, y=30), unit(2, x=31, y=30), unit(3, UnitTypeId.MEDIVAC, 30, 31))
    )
    result = Engine().allocate(
        frame,
        (
            proposal("defense:a", 1.0, count=1),
            proposal("offense", 0.0),
            proposal("core_army", -1.0, command=Command.HOLD),
        ),
    )

    report = behaviors.command_units(bot, result)

    assert report == attack.MicroReport(stimmed=(1, 2), escorts=(3,))


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


def test_holding_bio_stims_when_the_fight_reaches_the_rally() -> None:
    bot = FakeBot()
    marine = bio(1)
    bot.enemy_units = [FakeUnit(90, UnitTypeId.ZERGLING, 30 + attack.STIM_RANGE, 30)]
    hold = proposal("core_army", -1.0, command=Command.HOLD, target=Point2((30, 30)))

    report = behaviors.BY_COMMAND[Command.HOLD](bot, [marine], hold)

    assert [type(micro) for micro in maneuvers(bot)[1]] == [UseAbility, AMove]
    assert report.stimmed == (1,)

    # A worker in reach is fought, but no reason to stim.
    bot = FakeBot()
    bot.enemy_units = [FakeUnit(90, UnitTypeId.SCV, 32, 30)]
    report = behaviors.BY_COMMAND[Command.HOLD](bot, [marine], hold)
    assert [type(micro) for micro in maneuvers(bot)[1]] == [AMove]
    assert report.stimmed == ()

    # Nothing in reach: walk to the point, no stim.
    bot = FakeBot()
    bot.enemy_units = [FakeUnit(90, UnitTypeId.ZERGLING, 30.5 + attack.STIM_RANGE, 30)]
    report = behaviors.BY_COMMAND[Command.HOLD](bot, [marine], hold)
    assert [type(micro) for micro in maneuvers(bot)[1]] == [PathUnitToTarget]
    assert report.stimmed == ()

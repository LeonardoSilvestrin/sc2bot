from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from random import Random

import pytest
import yaml
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.awareness import AwarenessModel
from bot.body.behaviors import economy as economy_behavior
from bot.ego.planners import economy
from bot.ego.planners.economy import styles
from bot.ego.strategy import Objective, StrategyModel

from .fakes import FakeBot, attention
from .test_economy import Barracks

BUILDS = Path(__file__).resolve().parents[1] / "terran_builds.yml"


def mech_plan(objective: Objective = Objective.BUILD_ADVANTAGE):
    frame = attention(time=400.0, opening_done=True)
    strategy = StrategyModel().decide(frame, AwarenessModel().infer(frame))
    return economy.plan(frame, replace(strategy, objective=objective), styles.MECH)


def test_mech_is_drawn_only_against_zerg_and_bio_against_every_race() -> None:
    assert styles.candidates(Race.Zerg) == (styles.BIO, styles.MECH)
    for race in (Race.Protoss, Race.Terran, Race.Random):
        assert styles.candidates(race) == (styles.BIO,)


def test_the_draw_covers_every_candidate_and_a_forced_style_wins() -> None:
    rng = Random(0)
    drawn = {styles.choose(Race.Zerg, rng).name for _ in range(50)}

    assert drawn == {"bio", "mech"}
    assert styles.choose(Race.Protoss, rng, forced="mech") is styles.MECH
    with pytest.raises(ValueError):
        styles.choose(Race.Zerg, rng, forced="sky")


def test_the_announcement_names_the_style_and_its_units() -> None:
    assert styles.announcement(styles.MECH) == (
        "Hoje vai de MECH: Hellion, Cyclone e Siege Tank."
    )
    assert styles.announcement(styles.BIO) == (
        "Hoje vai de BIO: Marine, Marauder, Siege Tank e Medivac."
    )


@pytest.mark.parametrize("style", list(styles.STYLES.values()), ids=list(styles.STYLES))
def test_every_style_is_complete(style: styles.ArmyStyle) -> None:
    assert sum(proportion for _, proportion, _ in style.composition) == pytest.approx(1.0)
    assert style.reactor_on in economy_behavior.REACTOR_OF
    assert len(set(style.upgrades)) == len(style.upgrades)


@pytest.mark.parametrize("style", list(styles.STYLES.values()), ids=list(styles.STYLES))
def test_every_opening_is_a_build_ares_can_parse(style: styles.ArmyStyle) -> None:
    builds = yaml.safe_load(BUILDS.read_text(encoding="utf-8"))
    steps = builds["Builds"][style.opening]["OpeningBuildOrder"]
    known = {"supply", "gas", "orbital", "expand", "worker"}
    for step in steps:
        command = step.split(" ")[1]
        assert (
            command in known
            or command.upper() in UnitTypeId.__members__
            or command.upper() in UpgradeId.__members__
        ), step
    # Every race the style is drawn against lists its opening.
    for race in style.against:
        assert style.opening in builds["BuildChoices"][race.name]["Cycle"]


def test_the_mech_plan_builds_mech_and_puts_reactors_on_factories() -> None:
    plan = mech_plan()

    assert plan.army == "mech"
    assert plan.composition == styles.MECH.composition
    assert plan.upgrades == styles.MECH.upgrades
    assert (plan.reactors, plan.reactor_on) == (True, UnitTypeId.FACTORY)


def test_stabilizing_with_mech_still_spends_on_the_army_only() -> None:
    plan = mech_plan(Objective.STABILIZE)

    assert plan.freeflow and plan.upgrades == () and not plan.reactors
    # The composition does not change while stabilizing: Ares spends freely on it.
    assert plan.composition == styles.MECH.composition


def factories_bot(bare: int, reactors: int) -> tuple[FakeBot, list[Barracks]]:
    factories = [Barracks(tag) for tag in range(1, bare + 1)]
    for factory in factories:
        factory.type_id = UnitTypeId.FACTORY
    with_reactor = [Barracks(100 + tag, add_on=True) for tag in range(reactors)]
    bot = FakeBot()
    bot.minerals, bot.vespene = 500, 500
    bot.mediator.get_own_structures_dict[UnitTypeId.FACTORY] = factories + with_reactor
    bot.mediator.get_own_structures_dict[UnitTypeId.FACTORYREACTOR] = [
        object() for _ in range(reactors)
    ]
    return bot, factories


def add_reactor(bot: FakeBot) -> bool:
    plan = mech_plan()
    return economy_behavior.AddReactors(
        techlab_reserve=plan.techlab_reserve,
        structure=plan.reactor_on,
        reactor_share=plan.reactor_share,
    ).execute(bot, {}, bot.mediator)


def test_reactors_go_on_the_factories_the_plan_names_within_the_share() -> None:
    # 0.25 of the Factories: the first Reactor of four fits.
    bot, factories = factories_bot(bare=4, reactors=0)

    assert mech_plan().reactor_share == pytest.approx(0.25)
    assert add_reactor(bot)
    assert [factory.built for factory in factories] == [[UnitTypeId.FACTORYREACTOR], [], [], []]


def test_a_reactor_beyond_the_share_is_not_added() -> None:
    # Four Factories with one Reactor already: a second is past 0.25.
    bot, factories = factories_bot(bare=3, reactors=1)

    assert not add_reactor(bot)
    assert all(factory.built == [] for factory in factories)

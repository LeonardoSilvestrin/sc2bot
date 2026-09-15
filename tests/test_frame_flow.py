"""The only tests that drive a (fake) bot: one frame through every layer."""

from __future__ import annotations

import pytest
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.macro import MacroPlan, Mining
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from bot.attention import observe, read_map
from bot.awareness import AwarenessConfig
from bot.ego.planners import core_army, defense
from bot.ego.strategy import StrategyConfig
from bot.logs import Logs, OverlayConfig, SnapshotConfig
from bot.main import Layers, play_frame

from .fakes import MAIN, MAP, FakeBot, FakeLogger, FakeUnit

ARMY_TAGS = {200, 201, 202, 203, 204, 205, 300}


def build_bot(*, attackers: int = 3) -> FakeBot:
    bot = FakeBot()
    bot.units = [
        *(FakeUnit(100 + index, UnitTypeId.SCV, 12, 8 + index, dps=5.0) for index in range(4)),
        *(FakeUnit(200 + index, UnitTypeId.MARINE, 18 + index, 18) for index in range(6)),
        FakeUnit(300, UnitTypeId.SIEGETANK, 20, 20, dps=20.0, hit_points=175.0),
    ]
    command_center = FakeUnit(
        1, UnitTypeId.COMMANDCENTER, 10.5, 10.5, dps=0.0, hit_points=1500.0, structure=True
    )
    bot.structures = [command_center]
    bot.townhalls = [command_center]
    bot.enemy_units = [
        FakeUnit(900 + index, UnitTypeId.ZERGLING, 14 + index, 12, hit_points=35.0)
        for index in range(attackers)
    ]
    return bot


def grants(frame) -> dict[str, tuple[int, ...]]:
    return {grant.proposal.proposal_id: grant.tags for grant in frame.result.grants}


def test_a_frame_flows_from_attention_to_logs() -> None:
    logger = FakeLogger()
    bot = build_bot()

    frame = play_frame(bot, 7, Layers(map_view=MAP, logs=Logs(logger)))

    granted = grants(frame)
    (defended,) = [grant.tags for grant in frame.result.grants if grant.proposal.owner == "defense"]
    held = granted[core_army.OWNER]
    assert defended and held
    assert set(defended).isdisjoint(held)
    assert set(defended) | set(held) == ARMY_TAGS

    maneuvers = [item for item in bot.registered if isinstance(item, CombatManeuver)]
    commanded = [maneuver.micros[-1].unit.tag for maneuver in maneuvers]
    assert sorted(commanded) == sorted(ARMY_TAGS)
    assert any(isinstance(item, Mining) for item in bot.registered)
    assert any(isinstance(item, MacroPlan) for item in bot.registered)

    names = [event["name"] for event in logger.events]
    for name in (
        "attention.observed",
        "awareness.updated",
        "strategy.decided",
        "behavior.proposed",
        "behavior.economy_planned",
        "behavior.structures_planned",
        "engine.granted",
        "engine.commanded",
        "logs.frame_perf",
    ):
        assert name in names
    assert {event["iteration"] for event in logger.events} == {7}
    (command,) = [
        e for e in logger.named("engine.commanded") if e["data"]["owner"] == defense.OWNER
    ]
    assert command["data"]["tags"] == list(defended)
    assert command["data"]["command"] == "ATTACK"
    assert command["data"]["inputs"]["threat"] > 0.0
    assert set(command["data"]) >= {"attention", "awareness", "strategy", "reason", "priority"}

    # The causal trail of the defense: incident -> demand -> grant.
    updated = logger.named("awareness.updated")[0]["data"]
    (incident,) = updated["incidents"]
    assert incident["contacts"] == [900, 901, 902]
    assert updated["danger"] == updated["danger_now"] == updated["bases"][0]["recent_threat"]
    decided = logger.named("strategy.decided")[0]["data"]
    assert decided["inputs"]["danger_now"] == updated["danger_now"]
    (proposed,) = [
        item
        for item in logger.named("behavior.proposed")[0]["data"]["proposals"]
        if item["owner"] == defense.OWNER
    ]
    assert proposed["demand_id"] == command["data"]["demand_id"] == incident["incident_id"]
    assert proposed["must_attack"] == "GROUND"
    assert proposed["minimum_power"] == pytest.approx(1.5 * incident["power"])
    (grant,) = [
        item
        for item in logger.named("engine.granted")[0]["data"]["grants"]
        if item["owner"] == defense.OWNER
    ]
    assert (grant["status"], grant["reason"]) == ("FULL", "minimum_power_met")
    assert grant["granted_power"] >= grant["minimum_power"]
    assert grant["tags"] == list(defended)


def test_a_lowered_depot_in_the_attack_path_rises_and_the_log_says_why() -> None:
    logger = FakeLogger()
    bot = build_bot()
    depot = FakeUnit(
        2, UnitTypeId.SUPPLYDEPOTLOWERED, 16, 14, dps=0.0, hit_points=400.0, structure=True
    )
    bot.structures.append(depot)

    frame = play_frame(bot, 0, Layers(map_view=MAP, logs=Logs(logger)))

    assert frame.structures.raise_ == (2,)
    assert depot.commands == [AbilityId.MORPH_SUPPLYDEPOT_RAISE]
    (planned,) = logger.named("behavior.structures_planned")
    assert (planned["data"]["raise"], planned["data"]["reason"]) == ([2], "enemy_near")
    assert planned["data"]["inputs"]["enemy_near"] == 1.0


def test_a_worker_inside_a_gas_building_does_not_flip_the_economy_plan() -> None:
    # Counting listed units, 48 SCVs on three bases read 47 whenever one was
    # inside a refinery, so the plan flipped every step or two (trace 788af1d,
    # 362.9-367.3 s: expand with 5 gas against no expand with 4).
    logger = FakeLogger()
    bot = build_bot(attackers=0)
    bot.townhalls = [
        FakeUnit(
            1 + index, UnitTypeId.COMMANDCENTER, x, y, dps=0.0, hit_points=1500.0, structure=True
        )
        for index, (x, y) in enumerate(MAP.expansions)
    ]
    bot.structures = list(bot.townhalls)
    army = [unit for unit in bot.units if unit.type_id is not UnitTypeId.SCV]
    scvs = [
        FakeUnit(100 + index, UnitTypeId.SCV, 12, 8 + index % 4, dps=5.0) for index in range(48)
    ]
    layers = Layers(map_view=MAP, logs=Logs(logger))

    plans, workers, economies = [], [], []
    for iteration in range(8):
        # Every other step one SCV is inside a gas building.
        inside = iteration % 2
        bot.time = 300.0 + 0.5 * iteration
        bot.units = [*scvs[inside:], *army]
        bot.workers_in_gas = inside
        frame = play_frame(bot, iteration, layers)
        plans.append((frame.economy.bases, frame.economy.expand, frame.economy.gas))
        workers.append(frame.attention.workers)
        economies.append(frame.strategy.economy)

    assert set(plans) == {(4, True, 5)}
    assert set(workers) == {48}
    (planned,) = logger.named("behavior.economy_planned")
    assert planned["data"]["inputs"] == pytest.approx(
        {"workers": 48.0, "bases": 3.0, "saturated_at": 48.0, "strategy_economy": economies[0]}
    )


def test_the_fog_does_not_let_a_threatened_bot_expand_as_if_the_enemy_had_no_army() -> None:
    # Trace 3769f04, 240-560 s: with no enemy army in sight enemy_power was 0 and
    # army_share 1.0 until 45 Marines of it arrived at 575 s. Under that belief
    # a Zergling at the main barely moved the plan: a saturated bot with 9
    # Marines of army at 10 minutes still expanded, as if that Zergling were
    # the whole enemy army.
    logger = FakeLogger()
    bot = build_bot(attackers=1)
    bot.time = 600.0
    bot.townhalls = [
        FakeUnit(
            1 + index, UnitTypeId.COMMANDCENTER, x, y, dps=0.0, hit_points=1500.0, structure=True
        )
        for index, (x, y) in enumerate(MAP.expansions)
    ]
    bot.structures = list(bot.townhalls)
    army = [unit for unit in bot.units if unit.type_id is not UnitTypeId.SCV]
    scvs = [
        FakeUnit(100 + index, UnitTypeId.SCV, 12, 8 + index % 4, dps=5.0) for index in range(48)
    ]
    bot.units = [*scvs, *army]

    frame = play_frame(bot, 0, Layers(map_view=MAP, logs=Logs(logger)))

    assert frame.awareness.danger > 0.0
    assert frame.strategy.economy < 0.5
    assert (frame.economy.expand, frame.economy.reason) == (False, "build_economy")
    config = AwarenessConfig()
    expected = config.army_growth * (600.0 - config.army_onset)
    updated = logger.named("awareness.updated")[0]["data"]
    assert updated["enemy_power"] == pytest.approx(frame.awareness.incidents[0].power)
    assert updated["expected_enemy_power"] == pytest.approx(expected)
    assert updated["estimated_enemy_power"] == pytest.approx(expected)
    assert updated["enemy_uncertainty"] == pytest.approx(expected - updated["enemy_power"])
    decided = logger.named("strategy.decided")[0]["data"]["inputs"]
    assert decided["planned_enemy_power"] == pytest.approx(
        expected + StrategyConfig().commit_margin * updated["enemy_uncertainty"]
    )
    (planned,) = logger.named("behavior.economy_planned")
    assert planned["data"]["inputs"]["strategy_economy"] == pytest.approx(frame.strategy.economy)
    assert planned["data"]["expand"] is False


def test_units_return_to_the_core_army_when_the_attack_dies() -> None:
    bot = build_bot()
    layers = Layers(map_view=MAP, logs=Logs())
    play_frame(bot, 0, layers)

    bot.time = 1.0
    bot.state.dead_units = {enemy.tag for enemy in bot.enemy_units}
    bot.enemy_units = []
    bot.registered = []
    frame = play_frame(bot, 1, layers)

    assert grants(frame) == {core_army.OWNER: tuple(sorted(ARMY_TAGS))}


def test_the_same_game_replays_to_the_same_decisions() -> None:
    def replay():
        bot = build_bot(attackers=4)
        layers = Layers(map_view=MAP, logs=Logs())
        frames = []
        for iteration, time in enumerate((0.0, 0.5, 1.0, 9.0)):
            bot.time = time
            if time >= 9.0:
                bot.enemy_units = bot.enemy_units[:1]
            frame = play_frame(bot, iteration, layers)
            frames.append((frame.strategy, frame.proposals, frame.result))
        return frames

    assert replay() == replay()


def test_read_map_and_observe_read_what_the_layers_need() -> None:
    bot = build_bot()
    bot.enemy_units.append(FakeUnit(999, UnitTypeId.ROACH, 40, 40, visible=False))

    map_view = read_map(bot, lattice_spacing=4)
    frame = observe(bot, 3, map_view)

    assert map_view.lattice
    assert all(2.0 <= p.x <= 62.0 and 2.0 <= p.y <= 62.0 for p in map_view.lattice)
    assert list(map_view.lattice) == sorted(map_view.lattice, key=lambda p: (p.y, p.x))
    assert frame.workers == 4
    assert [base.base_id for base in frame.bases] == [MAIN.base_id]
    assert 999 not in {unit.tag for unit in frame.enemy_units}
    assert frame.opening == "BioThreeOneOne" and frame.opening_done


def test_debug_observers_draw_and_write_without_changing_decisions(tmp_path) -> None:
    def run(logs: Logs):
        bot = build_bot()
        layers = Layers(map_view=MAP, logs=logs)
        frames = []
        for iteration, time in enumerate((0.0, 1.0)):
            bot.time = time
            frame = play_frame(bot, iteration, layers)
            frames.append((frame.strategy, frame.result))
        return bot, frames

    logger = FakeLogger()
    observed_bot, observed = run(
        Logs(
            logger,
            overlay=OverlayConfig(enabled=True, draw_spacing=8.0),
            snapshots=SnapshotConfig(enabled=True, interval_seconds=0.5),
            snapshot_directory=tmp_path,
        )
    )
    _, silent = run(Logs())

    assert observed == silent
    assert observed_bot.client.spheres and observed_bot.client.screen_text
    assert (tmp_path / "field-0001.svg").is_file()
    assert (tmp_path / "latest.svg").is_file()
    assert logger.named("logs.snapshot_written")

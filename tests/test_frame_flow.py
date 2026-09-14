"""The only tests that drive a (fake) bot: one frame through every layer."""

from __future__ import annotations

from ares.behaviors.combat import CombatManeuver
from ares.behaviors.macro import MacroPlan, Mining
from sc2.ids.unit_typeid import UnitTypeId

from bot.attention import observe, read_map
from bot.ego.planners import core_army, defense
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
    defended = granted[f"defense:{MAIN.base_id}"]
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

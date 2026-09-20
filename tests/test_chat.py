"""The chat: what the bot says out loud, and how little of it."""

from __future__ import annotations

from dataclasses import replace

import pytest

from bot.awareness import AwarenessModel, OpeningBelief
from bot.ego.strategy import StrategicPosture, StrategyModel
from bot.logs import Chat, ChatConfig, Logs
from bot.logs.chat import LINES, OPENING_LOUD, OPENING_SURE

from .fakes import FakeLogger, attention

AWARENESS = AwarenessModel()
STRATEGY = StrategyModel()


def frame(time: float):
    return attention(time=time)


def layers(
    time: float,
    *,
    posture=StrategicPosture.DEVELOP,
    emergency=False,
    opening=None,
    cloak=None,
):
    state = frame(time)
    awareness = AWARENESS.infer(state)
    awareness = replace(
        awareness,
        opening=opening or OpeningBelief(),
        cloak_seen_at=cloak,
    )
    intent = replace(STRATEGY.decide(state, awareness), posture=posture, emergency=emergency)
    return state, awareness, intent


def observe(chat: Chat, time: float, **kwargs) -> list[str]:
    return [topic for topic, _ in chat.observe(*layers(time, **kwargs))]


def test_the_bot_says_it_is_being_rushed_when_it_turns_to_defend() -> None:
    chat = Chat()

    # The posture the game opens in is not news.
    assert observe(chat, 10.0) == []
    assert observe(chat, 100.0, posture=StrategicPosture.DEFEND) == ["rushed"]
    assert chat.drain() == (("rushed", LINES["rushed"][0]),)
    # And what was drained is gone.
    assert chat.drain() == ()


def test_every_posture_has_something_to_say_and_repeats_itself_differently() -> None:
    chat = Chat(ChatConfig(gap=0.0, topic_cooldown=0.0))
    observe(chat, 10.0)

    spoken = [
        observe(chat, 20.0 + index, posture=posture)
        for index, posture in enumerate(
            (
                StrategicPosture.DEFEND,
                StrategicPosture.PRESSURE,
                StrategicPosture.COMMIT,
                StrategicPosture.RECOVER,
                StrategicPosture.DEVELOP,
                StrategicPosture.DEFEND,
            )
        )
    ]

    assert spoken == [["rushed"], ["pressure"], ["commit"], ["recover"], ["develop"], ["rushed"]]
    lines = [line for _, line in chat.drain()]
    # The second time a topic comes up it does not read the same.
    assert lines[0] == LINES["rushed"][0]
    assert lines[-1] == LINES["rushed"][1]


def test_the_bot_says_what_it_read_of_the_opening_once_it_is_sure_enough() -> None:
    chat = Chat(ChatConfig(gap=0.0))
    observe(chat, 10.0)
    loud = OpeningBelief(aggression=0.8, proxy=0.7, greed=0.1, confidence=OPENING_SURE)

    # A read nobody backs stays to itself.
    assert observe(chat, 100.0, opening=replace(loud, confidence=OPENING_SURE - 0.01)) == []
    assert observe(chat, 110.0, opening=loud) == ["proxy", "aggression"]
    # And it does not repeat itself while it still believes the same thing.
    assert observe(chat, 120.0, opening=loud) == []


def test_a_quiet_opening_is_not_worth_saying() -> None:
    chat = Chat(ChatConfig(gap=0.0))
    observe(chat, 10.0)
    quiet = OpeningBelief(aggression=OPENING_LOUD - 0.01, confidence=0.9)

    assert observe(chat, 100.0, opening=quiet) == []


def test_the_bot_speaks_one_line_at_a_time_and_not_many_in_a_game() -> None:
    chat = Chat(ChatConfig(gap=12.0, topic_cooldown=0.0))
    observe(chat, 10.0)

    assert observe(chat, 100.0, posture=StrategicPosture.DEFEND) == ["rushed"]
    # Too soon: the next thing is held back.
    assert observe(chat, 105.0, posture=StrategicPosture.COMMIT) == []
    assert observe(chat, 120.0, posture=StrategicPosture.PRESSURE) == ["pressure"]

    capped = Chat(ChatConfig(gap=0.0, topic_cooldown=0.0, max_lines=2))
    observe(capped, 10.0)
    spoken = [
        observe(capped, 20.0 + index, posture=posture)
        for index, posture in enumerate(
            (StrategicPosture.DEFEND, StrategicPosture.COMMIT, StrategicPosture.RECOVER)
        )
    ]
    assert spoken == [["rushed"], ["commit"], []]


def test_a_one_shot_line_the_pace_swallowed_is_not_lost() -> None:
    chat = Chat(ChatConfig(gap=12.0))
    observe(chat, 10.0)
    observe(chat, 100.0, posture=StrategicPosture.DEFEND)

    # The cloak was seen while the bot was still saying the last thing ...
    assert observe(chat, 103.0, posture=StrategicPosture.DEFEND, cloak=102.0) == []
    # ... so it says it as soon as it can.
    assert observe(chat, 115.0, posture=StrategicPosture.DEFEND, cloak=102.0) == ["cloaked"]
    assert observe(chat, 130.0, posture=StrategicPosture.DEFEND, cloak=102.0) == []


def test_an_emergency_is_said_once_and_again_after_the_next_one() -> None:
    chat = Chat(ChatConfig(gap=0.0, topic_cooldown=30.0))
    observe(chat, 10.0)

    assert observe(chat, 100.0, emergency=True) == ["emergency"]
    assert observe(chat, 105.0, emergency=True) == []
    # It ended and came back: worth saying again, once the topic cooled down.
    observe(chat, 110.0, emergency=False)
    assert observe(chat, 115.0, emergency=True) == []
    observe(chat, 140.0, emergency=False)
    assert observe(chat, 145.0, emergency=True) == ["emergency"]


def test_a_silent_bot_says_nothing_at_all() -> None:
    chat = Chat(ChatConfig(enabled=False))

    assert observe(chat, 100.0, posture=StrategicPosture.DEFEND) == []
    assert chat.say("gg", 200.0, force=True) is None
    assert chat.announce("Hoje vai de BIO.", 0.0) is None
    assert chat.drain() == ()


def test_the_farewell_goes_out_whatever_the_pace_says() -> None:
    chat = Chat(ChatConfig(max_lines=0))

    assert chat.say("rushed", 100.0) is None
    assert chat.say("gg", 100.0, force=True) == ("gg", "gg")


def test_the_config_rejects_a_pace_that_makes_no_sense() -> None:
    with pytest.raises(ValueError):
        ChatConfig(gap=-1.0)
    with pytest.raises(ValueError):
        ChatConfig(max_lines=-1)


def test_everything_the_bot_says_is_written_to_the_log() -> None:
    logger = FakeLogger()
    logs = Logs(logger)
    state, awareness, intent = layers(100.0, posture=StrategicPosture.DEFEND)

    logs.announced(0.0, "Hoje vai de BIO: Marine, Marauder e Medivac.")
    logs.chat.observe(*layers(10.0))
    for topic, line in logs.chat.observe(state, awareness, intent):
        logs.telemetry.said(time=state.time, topic=topic, line=line)
    logs.game_ended(600.0, "Result.Victory")

    said = [(event["data"]["topic"], event["data"]["line"]) for event in logger.named("chat.said")]
    assert said == [
        ("army", "Hoje vai de BIO: Marine, Marauder e Medivac."),
        ("rushed", "Tô sendo rushado!"),
        ("gg", "gg"),
    ]
    # And it is still queued for whoever can actually speak.
    assert [line for _, line in logs.chat.drain()] == [
        "Hoje vai de BIO: Marine, Marauder e Medivac.",
        "Tô sendo rushado!",
        "gg",
    ]


def test_a_frame_queues_what_the_bot_thinks_without_touching_the_decision() -> None:
    from sc2.ids.unit_typeid import UnitTypeId

    from bot.logs import Logs as _Logs
    from bot.main import Layers, play_frame

    from .fakes import MAP, FakeUnit
    from .test_frame_flow import build_bot

    bot = build_bot(attackers=0)
    logs = _Logs()
    layers_ = Layers(map_view=MAP, logs=logs)
    bot.time = 100.0
    first = play_frame(bot, 0, layers_)

    # A pack of Zerglings walks into the mineral line.
    bot.enemy_units = [
        FakeUnit(950 + index, UnitTypeId.ZERGLING, 11 + index * 0.2, 11, hit_points=35.0)
        for index in range(14)
    ]
    bot.time = 200.0
    second = play_frame(bot, 1, layers_)

    # The bot went to DEFEND under the attack and said so; the decision is the
    # same one the planners made.
    assert second.intent.posture is StrategicPosture.DEFEND
    assert [topic for topic, _ in logs.chat.drain()] == ["rushed"]
    assert first.intent.posture is not StrategicPosture.DEFEND

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import (
    CRASH,
    DEFEAT,
    NO_RESULT,
    TIE,
    TIMEOUT,
    VICTORY,
    GameSpec,
    build_record,
    load_records,
    matrix,
    outcome,
    summarize,
    wilson,
)

IDENTITY = {"commit": "abc", "branch": "botbandido", "ares_commit": "def", "dirty": False}


def small_matrix(**changes):
    arguments = {
        "maps": ("A", "B"),
        "races": ("Zerg", "Protoss"),
        "difficulties": ("VeryHard",),
        "ai_builds": ("Macro",),
        "games": 2,
        "seed": 10,
        "game_time_limit": 900.0,
    }
    return matrix(**{**arguments, **changes})


def test_the_same_arguments_give_the_same_games_in_a_fixed_order() -> None:
    specs = small_matrix()

    assert specs == small_matrix()
    assert len(specs) == 8
    assert [spec.index for spec in specs] == list(range(8))
    assert [(spec.map_name, spec.enemy_race, spec.seed) for spec in specs[:4]] == [
        ("A", "Zerg", 10),
        ("A", "Protoss", 10),
        ("B", "Zerg", 10),
        ("B", "Protoss", 10),
    ]
    assert {spec.seed for spec in specs[4:]} == {11}
    assert len({spec.game_id for spec in specs}) == 8
    assert GameSpec.from_json(json.loads(json.dumps(specs[5].to_json()))) == specs[5]


@pytest.mark.parametrize(
    "changes",
    [{"games": 0}, {"game_time_limit": 0.0}, {"maps": ()}, {"races": ()}],
)
def test_an_empty_or_invalid_matrix_is_rejected(changes) -> None:
    with pytest.raises(ValueError):
        small_matrix(**changes)


@pytest.mark.parametrize(
    "result, game_time, exit_code, wall, expected",
    [
        ("Result.Victory", 612.0, 0, False, VICTORY),
        ("Result.Defeat", 404.0, 0, False, DEFEAT),
        # python-sc2 ends a game at its time limit as a Tie.
        ("Result.Tie", 900.1, 0, False, TIMEOUT),
        # The bot's last step is a few game loops short of the limit.
        ("Result.Tie", 899.91, 0, False, TIMEOUT),
        ("Result.Tie", 500.0, 0, False, TIE),
        (None, 480.0, 0, False, NO_RESULT),
        ("Result.Undecided", 480.0, 0, False, NO_RESULT),
        (None, None, 1, False, CRASH),
        ("Result.Victory", 612.0, 1, False, CRASH),
        (None, None, None, True, CRASH),
    ],
)
def test_every_game_gets_an_explicit_outcome(result, game_time, exit_code, wall, expected) -> None:
    assert (
        outcome(
            result=result,
            game_time=game_time,
            game_time_limit=900.0,
            exit_code=exit_code,
            wall_timed_out=wall,
        )
        == expected
    )


def test_a_record_ties_the_outcome_to_code_configuration_replay_and_log(tmp_path: Path) -> None:
    spec = small_matrix()[0]
    replay = tmp_path / "replay.SC2Replay"
    replay.write_bytes(b"replay")
    log = tmp_path / "log" / "game.jsonl"
    log.parent.mkdir()
    log.write_text(
        "\n".join(
            json.dumps(record)
            for record in (
                {"event": "logs.frame_perf", "data": {}},
                {
                    "event": "game.started",
                    "data": {"config_fingerprint": "f00d", "configs": {"strategy": "beef"}},
                },
            )
        ),
        encoding="utf-8",
    )

    record = build_record(
        spec,
        label="baseline",
        identity=IDENTITY,
        result="Result.Victory",
        game_time=700.0,
        exit_code=0,
        wall_timed_out=False,
        wall_seconds=95.0,
        replay=replay,
        log=log,
    )

    assert record["outcome"] == VICTORY
    assert record["build"] == IDENTITY
    assert (record["config_fingerprint"], record["configs"]) == ("f00d", {"strategy": "beef"})
    assert (record["replay"], record["log"]) == (str(replay), str(log))
    assert record["spec"] == spec.to_json()
    json.dumps(record, allow_nan=False)

    missing = build_record(
        spec,
        label="baseline",
        identity=IDENTITY,
        result=None,
        game_time=None,
        exit_code=None,
        wall_timed_out=True,
        wall_seconds=3600.0,
        replay=tmp_path / "none.SC2Replay",
        log=tmp_path / "none.jsonl",
        error="killed",
    )
    assert (missing["outcome"], missing["replay"], missing["log"]) == (CRASH, None, None)
    assert missing["config_fingerprint"] is None


def test_the_summary_counts_every_game_and_bounds_the_win_rate(tmp_path: Path) -> None:
    specs = small_matrix(maps=("A",), races=("Zerg",), games=4)
    outcomes = [
        ("Result.Victory", 600.0, 0, False),
        ("Result.Defeat", 400.0, 0, False),
        ("Result.Tie", 900.0, 0, False),
        (None, None, None, True),
    ]
    for spec, (result, game_time, exit_code, wall) in zip(specs, outcomes, strict=True):
        record = build_record(
            spec,
            label="run",
            identity=IDENTITY,
            result=result,
            game_time=game_time,
            exit_code=exit_code,
            wall_timed_out=wall,
            wall_seconds=1.0,
            replay=None,
            log=None,
        )
        directory = tmp_path / spec.game_id
        directory.mkdir()
        (directory / "result.json").write_text(json.dumps(record), encoding="utf-8")

    records = load_records(tmp_path)
    summary = summarize(records)

    assert [record["spec"]["index"] for record in records] == [0, 1, 2, 3]
    overall = summary["overall"]
    assert overall["games"] == 4
    assert overall["outcomes"] == {
        VICTORY: 1,
        DEFEAT: 1,
        TIE: 0,
        TIMEOUT: 1,
        CRASH: 1,
        NO_RESULT: 0,
    }
    assert overall["win_rate"] == 0.25
    low, high = overall["win_rate_95"]
    assert 0.0 < low < 0.25 < high < 1.0
    assert overall["mean_game_time"] == pytest.approx((600.0 + 400.0 + 900.0) / 3)
    assert list(summary["groups"]) == ["A/Zerg/VeryHard/Macro"]
    assert summary["builds"] == [json.dumps(IDENTITY, sort_keys=True)]


def test_the_wilson_interval_is_wide_with_few_games() -> None:
    assert wilson(0, 0) == (0.0, 1.0)
    low, high = wilson(1, 1)
    assert low == pytest.approx(0.2065, abs=1e-4)
    assert high == 1.0
    low, high = wilson(50, 100)
    assert (low, high) == (pytest.approx(0.4038, abs=1e-4), pytest.approx(0.5962, abs=1e-4))

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

import bench
import harness
import run
from harness import (
    CRASH,
    DEFEAT,
    NO_RESULT,
    NOT_PLAYED,
    TIE,
    TIMEOUT,
    VICTORY,
    Game,
    GameSpec,
    build_record,
    load_records,
    matrix,
    needs_replay,
    outcome,
    summarize,
    wilson,
)

IDENTITY = {"commit": "abc", "branch": "botbandido", "ares_commit": "def", "dirty": False}


SMALL = (
    Game("A", "Zerg", "Macro"),
    Game("A", "Protoss", "Macro"),
    Game("B", "Zerg", "Macro"),
    Game("B", "Protoss", "Macro"),
)


def small_matrix(**changes):
    arguments = {
        "games": SMALL,
        "difficulties": ("VeryHard",),
        "repeats": 2,
        "seed": 10,
        "game_time_limit": 900.0,
    }
    arguments.update(changes)
    return matrix(arguments.pop("games"), **arguments)


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


def test_each_army_style_is_its_own_cell_and_old_records_still_load() -> None:
    specs = small_matrix(games=SMALL[:1], repeats=1, armies=("bio", "mech"))

    assert [spec.army for spec in specs] == ["bio", "mech"]
    assert [spec.game_id for spec in specs] == [
        "000-A-Zerg-VeryHard-Macro-10-bio",
        "001-A-Zerg-VeryHard-Macro-10-mech",
    ]
    # A record written before the army axis existed: the bot drew its style.
    old = specs[0].to_json()
    del old["army"]
    assert GameSpec.from_json(old).army is None
    assert GameSpec.from_json(old).game_id == "000-A-Zerg-VeryHard-Macro-10"


@pytest.mark.parametrize(
    "changes",
    [{"repeats": 0}, {"game_time_limit": 0.0}, {"games": ()}, {"difficulties": ()}, {"armies": ()}],
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
        # Ares' on_start raised, python-sc2 resigned on the first step and the
        # game reported a defeat the bot never played (`bench/7jk`, specs 4/6).
        ("Result.Defeat", 0.0, 0, False, NOT_PLAYED),
        ("Result.Victory", 0.0, 0, False, NOT_PLAYED),
        # No result was reported: the process failed, it did not resign.
        (None, 0.0, 1, False, CRASH),
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
    specs = small_matrix(games=SMALL[:1], repeats=4)
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
        NOT_PLAYED: 0,
    }
    assert overall["played"] == 4
    assert overall["win_rate"] == 0.25
    low, high = overall["win_rate_95"]
    assert 0.0 < low < 0.25 < high < 1.0
    assert overall["mean_game_time"] == pytest.approx((600.0 + 400.0 + 900.0) / 3)
    assert list(summary["groups"]) == ["A/Zerg/VeryHard/Macro"]
    assert summary["builds"] == [json.dumps(IDENTITY, sort_keys=True)]


def test_a_game_the_bot_never_played_counts_in_no_rate_and_is_played_again(
    tmp_path: Path,
) -> None:
    """`bench/7jk`: Ares' on_start raised on two of the nine specs, the game
    reported `Result.Defeat` at game_time 0 with exit code 0, and the win rate
    counted two losses the bot never played."""

    specs = small_matrix(games=SMALL[:1], repeats=3)
    games = [
        ("Result.Victory", 600.0, 18.0),
        ("Result.Defeat", 400.0, 500.0),
        # The resignation of `bench/7jk/004`: 18.7 s of wall clock, no game.
        ("Result.Defeat", 0.0, 18.7),
    ]
    for spec, (result, game_time, wall_seconds) in zip(specs, games, strict=True):
        record = build_record(
            spec,
            label="run",
            identity=IDENTITY,
            result=result,
            game_time=game_time,
            exit_code=0,
            wall_timed_out=False,
            wall_seconds=wall_seconds,
            replay=None,
            log=None,
        )
        directory = tmp_path / spec.game_id
        directory.mkdir()
        (directory / "result.json").write_text(json.dumps(record), encoding="utf-8")

    records = load_records(tmp_path)
    assert [record["outcome"] for record in records] == [VICTORY, DEFEAT, NOT_PLAYED]

    overall = summarize(records)["overall"]
    assert (overall["games"], overall["played"]) == (3, 2)
    assert overall["outcomes"][NOT_PLAYED] == 1
    # One win in the two games that happened, not in the three that were asked
    # for, and the 0 s of the game that did not happen is not an average.
    assert overall["win_rate"] == 0.5
    assert overall["mean_game_time"] == pytest.approx(500.0)

    assert [needs_replay(record) for record in records] == [False, False, True]


def test_the_summary_applies_the_current_rule_to_what_a_record_stored() -> None:
    """A record keeps what the game reported, so a run recorded before the rule
    is summarized under it; one without those fields keeps its own verdict."""

    spec = small_matrix(games=SMALL[:1], repeats=1)[0]
    stored = {
        "spec": spec.to_json(),
        "outcome": DEFEAT,
        "result": "Result.Defeat",
        "game_time": 0.0,
        "exit_code": 0,
        "wall_timed_out": False,
        "build": IDENTITY,
    }
    older = {"spec": {"map_name": "A", "enemy_race": "Zerg", "difficulty": "VeryHard",
                      "ai_build": "Macro", "index": 0}, "outcome": DEFEAT, "build": IDENTITY}

    assert summarize([stored])["overall"]["outcomes"][NOT_PLAYED] == 1
    assert summarize([stored])["overall"]["played"] == 0
    assert summarize([older])["overall"]["outcomes"][DEFEAT] == 1
    assert needs_replay(older) is False


def test_the_wilson_interval_is_wide_with_few_games() -> None:
    assert wilson(0, 0) == (0.0, 1.0)
    low, high = wilson(1, 1)
    assert low == pytest.approx(0.2065, abs=1e-4)
    assert high == 1.0
    low, high = wilson(50, 100)
    assert (low, high) == (pytest.approx(0.4038, abs=1e-4), pytest.approx(0.5962, abs=1e-4))


# --- the two sizes of the bench matrix ---


def test_the_table_plays_every_race_against_a_rush_a_macro_and_a_drawn_build() -> None:
    base = harness.games_of("base")

    assert len(base) == 9
    for race in harness.RACES:
        assert [game.ai_build for game in base if game.race == race] == list(harness.AI_BUILDS)


def test_the_base_matrix_draws_one_map_for_the_whole_run() -> None:
    random.seed(0)

    runs = [harness.games_of("base") for _ in range(20)]

    for games in runs:
        # One map per run: the nine games are played side by side, not spread.
        assert len({game.map_name for game in games}) == 1
        assert games[0].map_name in harness.MAPS
    # And the next run draws again.
    assert len({games[0].map_name for games in runs}) > 1


def test_the_wide_table_is_the_nine_games_on_every_map() -> None:
    wide = harness.games_of("wide")

    assert len(wide) == 27
    assert {game.map_name for game in wide} == set(harness.MAPS)
    for map_name in harness.MAPS:
        on_this_map = [game for game in wide if game.map_name == map_name]
        assert [(game.race, game.ai_build) for game in on_this_map] == [
            (game.race, game.ai_build) for game in harness.games_of("base")
        ]


def test_an_axis_given_by_hand_replaces_that_column() -> None:
    pinned = harness.games_of("base", maps=["OnlyThisOne"])

    assert {game.map_name for game in pinned} == {"OnlyThisOne"}
    assert [(game.race, game.ai_build) for game in pinned] == [
        (game.race, game.ai_build) for game in harness.BASE
    ]
    assert {game.race for game in harness.games_of("wide", races=["Zerg"])} == {"Zerg"}
    assert len(harness.games_of("base", ai_builds=["Macro"])) == 3
    # The wide table is written down, so it is handed back as it is.
    assert harness.games_of("wide") is harness.WIDE


def test_what_a_run_plays_by_default_is_written_in_the_matrix_file() -> None:
    # The launch configurations pass no matrix: the file decides.
    assert harness.DEFAULT_MATRIX in harness.MATRICES
    assert harness.DEFAULT_LAUNCHER in (run.SINGLE, run.BUILDS, run.WIDE_MATRIX)
    # Both entry points take the matrix from the file, not from their flags.
    assert bench.parser().parse_args(["run", "--out", "x"]).matrix == harness.DEFAULT_MATRIX
    assert run.parse_local_args([]).matrix == harness.DEFAULT_LAUNCHER


def test_a_name_the_game_would_reject_fails_before_any_game_starts() -> None:
    from argparse import Namespace

    args = Namespace(races=["Zerg"], difficulties=["VeryHard"], ai_builds=["Random"])

    with pytest.raises(SystemExit, match="RandomBuild"):
        bench._check_names(args)

    bench._check_names(Namespace(**{**vars(args), "ai_builds": ["RandomBuild"]}))


# --- the launcher walks the same matrix, without recording anything ---


def launcher(*argv):
    return run.parse_local_args(list(argv))


INSTALLED = ["PersephoneAIE_v4", "TorchesAIE_v4", "IncorporealAIE_v4", "PylonAIE_v4"]


def test_one_local_game_is_still_one_local_game() -> None:
    (game,) = run.local_games(launcher("--enemy-race", "Zerg", "--ai-build", "Macro"), INSTALLED)

    map_name, race, build = game
    assert (race, build) == ("Zerg", "Macro")
    assert map_name in INSTALLED
    assert run.time_limit(launcher()) is None


def test_the_builds_mode_varies_only_how_the_ai_opens() -> None:
    games = run.local_games(launcher("--matrix", "builds", "--enemy-race", "Terran"), INSTALLED)

    assert len(games) == 3
    assert [game.ai_build for game in games] == list(harness.AI_BUILDS)
    # Same map and same race: the opening is the only thing that changed.
    assert len({(map_name, race) for map_name, race, _ in games}) == 1
    assert run.time_limit(launcher("--matrix", "builds")) == run.SWEEP_TIME_LIMIT


def test_the_wide_mode_walks_every_map_race_and_opening() -> None:
    games = run.local_games(launcher("--matrix", "wide"), INSTALLED)

    assert len(games) == 27
    assert {map_name for map_name, _, _ in games} == set(harness.WIDE_MAPS)
    assert {game.race for game in games} == set(harness.RACES)
    # The race asked for does not narrow a sweep of every race.
    assert run.local_games(launcher("--matrix", "wide", "--enemy-race", "Zerg"), INSTALLED) == games


def test_a_map_that_is_not_installed_is_left_out_of_the_sweep() -> None:
    (installed,) = harness.MAPS[:1]

    games = run.local_games(launcher("--matrix", "wide"), [installed])

    assert len(games) == 9
    assert {game.map_name for game in games} == {installed}


def test_a_time_limit_given_by_hand_wins() -> None:
    assert run.time_limit(launcher("--matrix", "wide", "--time-limit", "600")) == 600.0
    assert run.time_limit(launcher("--time-limit", "600")) == 600.0

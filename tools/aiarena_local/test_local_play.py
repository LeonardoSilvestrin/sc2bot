"""Contract checks for orchestration inputs/artifacts; these do not simulate SC2."""

import argparse
import json
import tomllib
import zipfile
from pathlib import Path

import pytest

from tools.aiarena_local import local_play as play


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    upstream = play.BOOTSTRAP
    bots = {}
    for name in ("basic_bot", "loser_bot"):
        bots[name] = {
            "id": name,
            "race": "T",
            "type": "python",
            "source": str(upstream / "bots" / name),
        }
    (tmp_path / "bots.json").write_text(json.dumps(bots), encoding="utf-8")
    monkeypatch.setattr(play, "HERE", tmp_path)
    monkeypatch.setattr(play, "RUNTIME", tmp_path / "runtime")
    maps = tmp_path / "runtime/maps"
    maps.mkdir(parents=True)
    (maps / "FixtureAIE.SC2Map").write_bytes(b"test input, not a playable map")
    return tmp_path


def prepare():
    return play.prepare_run("basic_bot", "loser_bot", "FixtureAIE", 2240, 120)


def test_official_input_contract_and_isolated_artifacts(isolated):
    run_dir, manifest = prepare()
    config = tomllib.loads((run_dir / "config.toml").read_text())
    assert config["RUN_TYPE"] == "local"
    assert config["BASE_WEBSITE_URL"] == ""
    assert config["ROUNDS_PER_RUN"] == 1
    assert config["MAX_GAME_TIME"] == 2240
    assert config["MAX_REAL_TIME"] == 120
    assert (run_dir / "matches").read_text().strip().split(",") == [
        "basic_bot",
        "basic_bot",
        "T",
        "python",
        "loser_bot",
        "loser_bot",
        "T",
        "python",
        "FixtureAIE",
    ]
    overrides = json.loads((run_dir / "compose.override.json").read_text())
    assert len(overrides["services"]) == 4
    for service in overrides["services"].values():
        for mount in service["volumes"]:
            assert Path(mount["source"]).is_relative_to(run_dir)
            assert Path(mount["source"]).exists()
    assert manifest["status"] == "prepared"
    second, _ = prepare()
    assert second != run_dir


@pytest.mark.parametrize("result", ["InitializationError", "Player1Crash", "Player2TimeOut"])
def test_failed_game_is_never_success(isolated, result):
    run_dir, _ = prepare()
    play.write_json(run_dir / "results.json", {"results": [{"type": result, "game_steps": 20}]})
    with pytest.raises(RuntimeError, match="did not complete normally"):
        play.verify_result(run_dir)


def test_success_requires_played_frames_replay_and_both_bot_logs(isolated):
    run_dir, _ = prepare()
    result = {"type": "Player1Win", "game_steps": 0}
    play.write_json(run_dir / "results.json", {"results": [result]})
    with pytest.raises(RuntimeError, match="did not complete normally"):
        play.verify_result(run_dir)
    result["game_steps"] = 100
    play.write_json(run_dir / "results.json", {"results": [result]})
    with pytest.raises(RuntimeError, match="without a replay"):
        play.verify_result(run_dir)
    (run_dir / "replays/test.SC2Replay").write_bytes(b"fixture")
    with pytest.raises(RuntimeError, match="Missing bot"):
        play.verify_result(run_dir)
    for number, name in enumerate(("basic_bot", "loser_bot"), 1):
        path = run_dir / f"logs/bot_controller{number}/{name}/stderr.log"
        path.parent.mkdir()
        path.write_text("fixture")
    assert play.verify_result(run_dir) == result


@pytest.mark.parametrize("name", ["../escape.py", "/absolute.py", "C:/escape.py", "..\\escape.py"])
def test_downloaded_archive_cannot_escape_destination(tmp_path, name):
    archive = tmp_path / "bot.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(name, "invalid")
    with pytest.raises(ValueError, match="Unsafe path"):
        play.extract_zip(archive, tmp_path / "out")


def test_register_downloaded_zip_with_enclosing_folder(isolated):
    archive = isolated / "download.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("package/run.py", "print('fixture')")
    play.register_bot("downloaded", archive, "Z", "python")
    assert (isolated / "runtime/bots/downloaded/run.py").exists()
    assert play.registry()["downloaded"]["race"] == "Z"
    with pytest.raises(ValueError, match="already registered"):
        play.register_bot("downloaded", archive, "Z", "python")


def test_missing_engine_records_failure_instead_of_fake_result(isolated, monkeypatch):
    def unavailable():
        raise RuntimeError("fixture: engine unavailable")

    monkeypatch.setattr(play, "docker_ready", unavailable)
    args = argparse.Namespace(
        bot="basic_bot",
        opponent="loser_bot",
        map="FixtureAIE",
        max_game_time=2240,
        max_real_time=120,
        prepare_only=False,
    )
    assert play.run_match(args) == 2
    run_dir = next((isolated / "runs").iterdir())
    assert json.loads((run_dir / "manifest.json").read_text())["status"] == "failed"
    assert json.loads((run_dir / "results.json").read_text()) == {"results": []}

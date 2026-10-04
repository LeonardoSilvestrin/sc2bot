"""Contracts between the launcher, ladder packages, and benchmark records."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import ClientSession, web
from s2clientprotocol import sc2api_pb2 as sc_pb
from sc2.data import Result

import bench
import run
from harness import GameSpec
from tools.aiarena_local import live_play, local_play


@pytest.fixture
def ladder_package(tmp_path, monkeypatch):
    source = tmp_path / "runtime/bots/PhantomBot"
    (source / "data").mkdir(parents=True)
    (source / "run.py").write_text("print('fixture')")
    (source / "data/params.json").write_text('{"learning": 1}')
    monkeypatch.setattr(local_play, "HERE", tmp_path)
    monkeypatch.setattr(
        local_play,
        "registry",
        lambda: {
            "PhantomBot": {
                "source": "runtime/bots/PhantomBot",
                "type": "python",
                "race": "Z",
                "version": "fixture",
            },
        },
    )
    return source


def test_actual_opponent_package_and_learning_data_are_fingerprinted(ladder_package):
    before = live_play.opponent_info("PhantomBot")
    assert before["race"] == "Z"
    assert before["version"] == "fixture"
    (ladder_package / "data/params.json").write_text('{"learning": 2}')
    assert live_play.opponent_info("PhantomBot")["source_sha256"] != before["source_sha256"]


def test_unregistered_opponent_fails_before_starting_docker(ladder_package):
    with pytest.raises(ValueError, match="não cadastrado"):
        live_play.opponent_info("UnknownBot")


def test_docker_command_preserves_paths_and_ladder_port_contract():
    source = Path("C:/pasta com espaços/PhantomBot")
    command = live_play.docker_command("docker.exe", "fixture", source, 12345, 23450)
    assert command[command.index("--mount") + 1] == f"type=bind,source={source},target=/bot"
    assert command[command.index("--GamePort") + 1] == "12345"
    assert command[command.index("--StartPort") + 1] == "23450"
    assert command[command.index("--LadderServer") + 1] == "host.docker.internal"
    assert "--RealTime" not in command  # PhantomBot's entrypoint does not accept it.


def test_legacy_runtime_uses_python311_even_when_match_copy_is_named_opponent():
    source = Path("C:/partida/opponent")
    info = {"runtime": "python311"}
    runtime = local_play.opponent_runtime(info)
    command = live_play.docker_command("docker.exe", "fixture", source, 12345, 23450, info=info)
    assert command[command.index("--entrypoint") + 1] == runtime["python"]
    assert runtime["image"] in command
    assert local_play.BOT_IMAGE not in command


def test_ladder_bench_records_opponent_repeats_maps_and_armies(ladder_package):
    args = bench.parser().parse_args(
        [
            "run",
            "--out",
            "bench/fixture",
            "--opponent",
            "PhantomBot",
            "--maps",
            "A",
            "B",
            "--games",
            "2",
            "--seed",
            "7",
            "--armies",
            "bio",
            "mech",
        ]
    )
    specs = bench._specs(args)
    assert len(specs) == 8
    assert {spec.seed for spec in specs} == {7, 8}
    assert {spec.map_name for spec in specs} == {"A", "B"}
    assert {spec.army for spec in specs} == {"bio", "mech"}
    assert {spec.enemy_race for spec in specs} == {"Zerg"}
    assert all(
        spec.opponent == "PhantomBot" and spec.opponent_version == "fixture" for spec in specs
    )
    assert all(spec.opponent_sha256 for spec in specs)
    assert len({spec.game_id for spec in specs}) == 8
    assert GameSpec.from_json(specs[0].to_json()) == specs[0]


def test_ladder_bench_rejects_builtin_ai_flags(ladder_package):
    args = bench.parser().parse_args(
        [
            "run",
            "--out",
            "bench/fixture",
            "--opponent",
            "PhantomBot",
            "--races",
            "Terran",
        ]
    )
    with pytest.raises(SystemExit, match="define raça e build"):
        bench._specs(args)


def test_ladder_bench_does_not_mix_different_packages_in_same_output(
    ladder_package,
    tmp_path,
    monkeypatch,
):
    args = bench.parser().parse_args(
        [
            "run",
            "--out",
            str(tmp_path / "bench"),
            "--opponent",
            "PhantomBot",
        ]
    )
    out = args.out
    out.mkdir()
    specs = bench._specs(args)
    (out / "matrix.json").write_text(json.dumps({"games": [spec.to_json() for spec in specs]}))
    (ladder_package / "run.py").write_text("print('different version')")
    monkeypatch.setattr(bench, "_check_maps", lambda _: None)
    monkeypatch.setattr(bench, "identity", lambda: {})
    with pytest.raises(SystemExit, match="outra seleção/versão"):
        bench._run(args)


def test_builtin_records_keep_previous_shape_and_launcher_default():
    spec = GameSpec(0, "A", "Zerg", "VeryHard", "Macro", 1, 120)
    assert "opponent" not in spec.to_json()
    assert spec.game_id == "000-A-Zerg-VeryHard-Macro-1"
    assert run.parse_local_args([]).opponent == "builtin"
    args = run.parse_local_args(["--opponent", "PhantomBot", "--map", "A"])
    assert args.opponent == "PhantomBot" and args.map_name == "A"


def test_switching_existing_ladder_bench_to_builtin_also_requires_another_output(
    ladder_package,
    tmp_path,
    monkeypatch,
):
    out = tmp_path / "bench"
    out.mkdir()
    ladder = bench.parser().parse_args(
        [
            "run",
            "--out",
            str(out),
            "--opponent",
            "PhantomBot",
        ]
    )
    (out / "matrix.json").write_text(
        json.dumps(
            {
                "games": [spec.to_json() for spec in bench._specs(ladder)],
            }
        )
    )
    builtin = bench.parser().parse_args(
        [
            "run",
            "--out",
            str(out),
            "--matrix",
            "base",
            "--maps",
            "A",
        ]
    )
    monkeypatch.setattr(bench, "_check_maps", lambda _: None)
    monkeypatch.setattr(bench, "identity", lambda: {})
    with pytest.raises(SystemExit, match="outra seleção/versão"):
        bench._run(builtin)


def test_websocket_relay_preserves_response_ids_results_and_translates_quit():
    async def exercise():
        observation = sc_pb.Response(id=41, status=sc_pb.ended)
        observation.observation.observation.game_loop = 224
        observation.observation.player_result.add(player_id=1, result=sc_pb.Victory)
        observation.observation.player_result.add(player_id=2, result=sc_pb.Defeat)
        leave = sc_pb.Response(id=42, status=sc_pb.ended, leave_game=sc_pb.ResponseLeaveGame())
        upstream = SimpleNamespace(sent=[], responses=iter((observation, leave)))

        async def send(raw):
            upstream.sent.append(sc_pb.Request.FromString(raw))

        async def receive():
            return next(upstream.responses).SerializeToString()

        upstream.send_bytes, upstream.receive_bytes = send, receive
        relay = live_play.Relay(SimpleNamespace(_ws=upstream))
        app = web.Application()
        app.router.add_get("/sc2api", relay.handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with (
                ClientSession() as session,
                session.ws_connect(f"http://127.0.0.1:{port}/sc2api") as ws,
            ):
                await ws.send_bytes(
                    sc_pb.Request(
                        id=41,
                        observation=sc_pb.RequestObservation(),
                    ).SerializeToString()
                )
                response = sc_pb.Response.FromString(await ws.receive_bytes())
                assert response == observation
                await ws.send_bytes(
                    sc_pb.Request(id=42, quit=sc_pb.RequestQuit()).SerializeToString()
                )
                response = sc_pb.Response.FromString(await ws.receive_bytes())
                assert response.id == 42
            assert await relay.closed is None
            assert relay.results == {1: Result.Victory, 2: Result.Defeat}
            assert relay.game_loop == 224
            assert upstream.sent[0].id == 41
            assert upstream.sent[1].HasField("leave_game")
            assert upstream.sent[1].id == 42
        finally:
            await runner.cleanup()

    asyncio.run(exercise())


def test_native_deadline_is_recorded_as_wall_timeout(tmp_path, ladder_package, monkeypatch):
    from sc2 import maps

    spec = GameSpec(0, "A", "Zerg", "Ladder", "PhantomBot", 1, 120, opponent="PhantomBot")
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec.to_json()))
    monkeypatch.setattr(maps, "get", lambda _: None)

    def timed_out(*args, **kwargs):
        raise TimeoutError("fixture: native match deadline")

    monkeypatch.setattr(live_play, "play_match", timed_out)
    assert bench._play(spec_path, tmp_path, spatial_view=False, spatial_snapshot=False) == 1
    child = json.loads((tmp_path / "child.json").read_text())
    assert child["wall_timed_out"] is True
    assert child["result"] is None
    assert "native match deadline" in child["error"]

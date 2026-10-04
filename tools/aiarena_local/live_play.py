"""Windowed local games: native SC2 and BotBandido, Linux opponent in Docker."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
from contextlib import AsyncExitStack, suppress
from datetime import UTC, datetime
from pathlib import Path

from aiohttp import WSMsgType, web
from s2clientprotocol import sc2api_pb2 as sc_pb
from sc2.data import PlayerType, Race, Result
from sc2.main import _play_game, _setup_host_game
from sc2.player import AbstractPlayer
from sc2.portconfig import Portconfig
from sc2.sc2process import SC2Process

from . import local_play as local

SC2_BUILD = 75689
SC2_DATA = "B89B5D6FA7CBF6452E721311BFBC6CB2"
RACES = {"T": "Terran", "Z": "Zerg", "P": "Protoss", "R": "Random"}


def opponent_info(name: str) -> dict:
    """Validate before opening windows; fingerprint the actual local package/data."""
    local.validate_name(name)
    bots = local.registry()
    if name not in bots:
        raise ValueError(f"Bot {name!r} não cadastrado. Use run_local_opponent.py --list-bots.")
    info = dict(bots[name])
    if info["source"] == "project" or info["type"] != "python":
        raise ValueError("O modo com janela aceita adversários Python da ladder.")
    source = (local.HERE / info["source"]).resolve()
    if not (source / "run.py").is_file():
        raise ValueError(f"Entrypoint do adversário ausente: {source / 'run.py'}")
    digest = hashlib.sha256()
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(source).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    info.update(name=name, source=str(source), source_sha256=digest.hexdigest())
    return info


def docker_command(
    docker: str, name: str, source: Path, port: int, start: int, *, info: dict | None = None
) -> list[str]:
    # A list keeps Windows paths with spaces intact; no shell interpolation.
    runtime = local.opponent_runtime(info or {})
    return [
        docker,
        "run",
        "--rm",
        "--init",
        "--name",
        name,
        "--platform",
        "linux/amd64",
        "--mount",
        f"type=bind,source={source},target=/bot",
        "--workdir",
        "/bot",
        "--env",
        "PYTHONUNBUFFERED=1",
        "--entrypoint",
        runtime["python"],
        runtime["image"],
        "run.py",
        "--GamePort",
        str(port),
        "--StartPort",
        str(start),
        "--LadderServer",
        "host.docker.internal",
        "--OpponentId",
        "local-botbandido",
    ]


class Relay:
    """One WebSocket, forwarded unchanged to the opponent's native SC2 client.

    Only quit becomes leave_game: the launcher owns the SC2 process. There is
    no receive timeout, so a breakpoint in our bot can pause the stepped game.
    """

    def __init__(self, controller):
        self.controller = controller
        self.closed = asyncio.get_running_loop().create_future()
        self.results = {}
        self.game_loop = 0
        self.connected = False

    async def handle(self, request):
        if self.connected:
            raise web.HTTPConflict(text="Opponent already connected")
        self.connected = True
        ws = web.WebSocketResponse(max_msg_size=0)
        await ws.prepare(request)
        error = None
        try:
            async for msg in ws:
                if msg.type != WSMsgType.BINARY:
                    if msg.type == WSMsgType.ERROR:
                        raise ConnectionError(str(ws.exception()))
                    continue
                query = sc_pb.Request.FromString(msg.data)
                if query.HasField("join_game"):
                    print("Adversário conectado ao SC2; entrando na partida.", flush=True)
                quitting = query.HasField("quit")
                if quitting:
                    query = sc_pb.Request(id=query.id, leave_game=sc_pb.RequestLeaveGame())
                await self.controller._ws.send_bytes(query.SerializeToString())
                raw = await self.controller._ws.receive_bytes()
                response = sc_pb.Response.FromString(raw)
                if response.HasField("observation"):
                    obs = response.observation
                    self.game_loop = max(self.game_loop, obs.observation.game_loop)
                    self.results.update({p.player_id: Result(p.result) for p in obs.player_result})
                await ws.send_bytes(raw)
                if quitting:
                    break
        except Exception as exc:
            error = str(exc)
        finally:
            await ws.close()
            if not self.closed.done():
                self.closed.set_result(error)
        return ws


async def _match(player, game_map, info, directory, replay, time_limit, seed, docker, container):
    from sc2.paths import Paths

    executable = Paths.BASE / "Versions" / f"Base{SC2_BUILD}" / "SC2_x64.exe"
    if not executable.is_file():
        raise RuntimeError(f"SC2 4.10 nativo ausente: {executable}")
    opponent = AbstractPlayer(PlayerType.Participant, Race[RACES[info["race"]]], name=info["name"])
    ports = None
    process = None
    own = None
    waiter = None
    runner = None
    stack = AsyncExitStack()
    controllers = []
    output = (directory / "opponent.txt").open("w", encoding="utf-8")
    try:
        for placement in ((0, 0), (1040, 0)):
            controller = await stack.enter_async_context(
                SC2Process(
                    host="127.0.0.1",
                    base_build=f"Base{SC2_BUILD}",
                    data_hash=SC2_DATA,
                    fullscreen=False,
                    resolution=(1024, 768),
                    placement=placement,
                )
            )
            ping = await controller.ping()
            if ping.ping.base_build != SC2_BUILD:
                raise RuntimeError(f"Build SC2 inesperado: {ping.ping.base_build}")
            controllers.append(controller)
        client = await _setup_host_game(
            controllers[0],
            game_map,
            [player, opponent],
            False,
            seed,
        )
        relay = Relay(controllers[1])
        app = web.Application()
        app.router.add_get("/sc2api", relay.handle)
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        # Pick LAN ports after both SC2 API sockets and the relay are bound.
        # Otherwise Windows can reuse an unbound LAN port for an API socket.
        ports = Portconfig.contiguous_ports()
        source = directory / "opponent"
        shutil.copytree(info["source"], source)
        process = await asyncio.create_subprocess_exec(
            *docker_command(docker, container, source, port, ports.server[0] - 2, info=info),
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        own = asyncio.create_task(_play_game(player, client, False, ports, time_limit))
        waiter = asyncio.create_task(process.wait())
        done, _ = await asyncio.wait(
            [own, waiter, relay.closed], return_when=asyncio.FIRST_COMPLETED
        )
        if own not in done:
            if not relay.results:
                error = relay.closed.result() if relay.closed.done() else process.returncode
                raise RuntimeError(
                    f"Adversário desconectou sem resultado: {error}. "
                    f"Veja {directory / 'opponent.txt'}"
                )
            result = await asyncio.wait_for(own, timeout=30)
        else:
            result = own.result()
        if result not in (Result.Victory, Result.Defeat, Result.Tie):
            raise RuntimeError(f"Partida terminou sem resultado válido: {result}")
        await client.save_replay(str(replay))
        if not replay.is_file() or replay.stat().st_size == 0:
            raise RuntimeError("Partida terminou sem replay.")
        return result
    finally:
        # Remove only this match's container, including after Ctrl+C or a breakpoint timeout.
        if process is not None:
            cleanup = await asyncio.create_subprocess_exec(
                docker,
                "rm",
                "--force",
                container,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            with suppress(TimeoutError):
                await asyncio.wait_for(cleanup.wait(), timeout=20)
            with suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=10)
        for controller in controllers:
            await controller._process._close_connection()
        for task in (own, waiter):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (own, waiter) if task), return_exceptions=True)
        if runner is not None:
            await runner.cleanup()
        output.close()
        if ports is not None:
            ports.clean()
        await stack.aclose()


def play_match(
    player,
    game_map,
    opponent,
    *,
    directory=None,
    replay=None,
    time_limit=None,
    seed=None,
    wall_timeout=7200,
    expected_sha256=None,
):
    """Run our bot in this process, so VS Code breakpoints and overlays work."""
    if os.name != "nt":
        raise RuntimeError("O modo com janela precisa do StarCraft II instalado no Windows.")
    info = opponent_info(opponent)
    if expected_sha256 and info["source_sha256"] != expected_sha256:
        raise ValueError("O pacote do adversário mudou desde a preparação do bench.")
    player.ai.opponent_id = info.get("id") or info["name"]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    container = f"sc2bot-live-{stamp.lower()}-{os.getpid()}"
    directory = Path(directory or local.HERE / "runs" / f"{stamp}-live-vs-{opponent}").resolve()
    directory.mkdir(parents=True, exist_ok=True)
    replay = Path(replay or directory / "replay.SC2Replay").resolve()
    manifest = {
        "mode": "live",
        "status": "preparing",
        "sc2_build": SC2_BUILD,
        "map": game_map.name,
        "opponent": info,
        "seed": seed,
        "time_limit": time_limit,
        "replay": str(replay),
        "container": container,
        "log": str(player.ai.bot_logs.logger.path)
        if hasattr(player.ai.bot_logs.logger, "path")
        else None,
    }
    path = directory / "live-manifest.json"
    local.write_json(path, manifest)
    print(f"Partida com janela: BotBandido vs {opponent}. Artefatos: {directory}", flush=True)
    try:
        docker = local.docker_ready()
        runtime = local.ensure_opponent_image(docker, info, directory / "setup.log")
        image_info = local.command(
            [docker, "image", "inspect", runtime["image"], "--format", "{{.Id}}"]
        )
        manifest["opponent_runtime"] = {
            "image": runtime["image"],
            "image_id": image_info.strip(),
            "python": runtime["python"],
        }
        manifest["status"] = "running"
        local.write_json(path, manifest)

        async def limited():
            return await asyncio.wait_for(
                _match(
                    player, game_map, info, directory, replay, time_limit, seed, docker, container
                ),
                timeout=wall_timeout,
            )

        result = asyncio.run(limited())
        manifest.update(status="completed", result=str(result), game_time=float(player.ai.time))
        return result
    except BaseException as exc:
        manifest.update(status="failed", error=str(exc) or type(exc).__name__)
        raise
    finally:
        local.write_json(path, manifest)

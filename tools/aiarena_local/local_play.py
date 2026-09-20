"""Prepare inputs and invoke official AI Arena Compose; no match controller here."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOOTSTRAP = HERE / "bootstrap"
BOOTSTRAP_COMMIT = "6de4228a79d61bb045a0f179573c07984355f53f"
BOOTSTRAP_URL = "https://github.com/aiarena/local-play-bootstrap.git"
RUNTIME = HERE / "runtime"
SC2_IMAGE = (
    "aiarena/arenaclient-sc2:v0.8.0@"
    "sha256:9d411a5d014760882fb165a1deef9bc98610f6e272d982439b1890b935a351ff"
)
BOT_IMAGE = (
    "aiarena/arenaclient-bot:v0.8.0@"
    "sha256:584ac823ac4a7871542c294ae4ccf2a0c87cc8a4281439989e405c674ea8e0f2"
)
PROXY_IMAGE = (
    "aiarena/arenaclient-proxy:v0.8.0@"
    "sha256:ab63d24cb854156f0c8f40a179c2d4cf1fd44f7889341b01e6f5b833dc3ea43c"
)
NORMAL_RESULTS = {"Player1Win", "Player2Win", "Tie"}
BOT_TYPES = {
    "python": "run.py",
    "cpplinux": "{name}",
    "cppwin32": "{name}.exe",
    "dotnetcore": "{name}.dll",
    "java": "{name}.jar",
    "nodejs": "{name}.js",
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def command(args, *, cwd=ROOT, timeout=120, log=None):
    args = [str(a) for a in args]
    if log is not None:
        with log.open("a", encoding="utf-8") as stream:
            stream.write("\n$ " + subprocess.list2cmdline(args) + "\n")
            stream.flush()
            result = subprocess.run(
                args, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout, check=False
            )
    else:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    if result.returncode:
        detail = f"See {log}" if log else (result.stdout + result.stderr).strip()
        raise RuntimeError(f"Command exited {result.returncode}: {args[0]}\n{detail}")
    return (result.stdout or "") if log is None else ""


def docker_path():
    candidates = [shutil.which("docker")]
    if os.name == "nt":
        candidates += [
            r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
            str(
                Path(os.environ.get("LOCALAPPDATA", ""))
                / "Programs/DockerDesktop/resources/bin/docker.exe"
            ),
        ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            # A terminal opened before installation may not have Docker's credential helpers.
            directory = str(Path(candidate).parent)
            os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
            return str(candidate)
    raise RuntimeError("Docker CLI missing. Install Docker Desktop with Linux containers/WSL 2.")


def docker_ready():
    docker = docker_path()
    command([docker, "compose", "version"], timeout=30)
    info = json.loads(command([docker, "info", "--format", "{{json .}}"], timeout=30))
    if info.get("OSType") != "linux":
        raise RuntimeError("Docker must run Linux containers (WSL 2 on Windows).")
    if info.get("Architecture") not in {"x86_64", "amd64"}:
        raise RuntimeError("This setup requires an x86_64 Linux Docker engine for SC2 75689.")
    return docker


def sc2_locations():
    candidates = [
        os.environ.get("SC2PATH", ""),
        r"C:\Program Files (x86)\StarCraft II",
        r"C:\Program Files\StarCraft II",
        r"C:\Games\StarCraft II",
        str(Path.home() / "StarCraftII"),
        "/Applications/StarCraft II",
    ]
    execute_info = Path.home() / "Documents/StarCraft II/ExecuteInfo.txt"
    if execute_info.is_file():
        match = re.search(r"=\s*(.*?)Versions", execute_info.read_text(errors="replace"))
        if match:
            candidates.insert(0, match[1].strip())
    return list(
        dict.fromkeys(
            Path(p).resolve() for p in candidates if p and (Path(p) / "Versions").is_dir()
        )
    )


def doctor():
    report = {
        "time": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python": sys.version,
        "expected_sc2_build": 75689,
        "sc2_image": SC2_IMAGE,
        "native_sc2": [
            {"path": str(p), "builds": sorted(x.name for x in (p / "Versions").glob("Base*"))}
            for p in sc2_locations()
        ],
    }
    try:
        docker = docker_path()
        report["docker_version"] = command([docker, "--version"]).strip()
        report["compose_version"] = command([docker, "compose", "version"]).strip()
        docker_ready()
        report["docker_ready"] = True
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        report.update(docker_ready=False, blocker=str(exc))
    if os.name == "nt":
        for key, args in {
            "wsl_status": ["wsl", "--status"],
            "wsl_version": ["wsl", "--version"],
        }.items():
            try:
                result = subprocess.run(args, capture_output=True, timeout=30, check=False)
                raw = result.stdout + result.stderr
                encoding = "utf-16-le" if b"\x00" in raw else "utf-8"
                report[key] = raw.decode(encoding, errors="replace").strip()
            except (OSError, subprocess.TimeoutExpired) as exc:
                report[key] = str(exc)
    write_json(HERE / "host-report.json", report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["docker_ready"] else 2


def setup(maps_from=None):
    if not BOOTSTRAP.exists():
        command(["git", "clone", BOOTSTRAP_URL, BOOTSTRAP], timeout=300)
        command(["git", "checkout", "--detach", BOOTSTRAP_COMMIT], cwd=BOOTSTRAP)
    revision = command(["git", "rev-parse", "HEAD"], cwd=BOOTSTRAP).strip()
    if revision != BOOTSTRAP_COMMIT:
        raise RuntimeError(
            f"Unexpected bootstrap revision: {revision}; expected {BOOTSTRAP_COMMIT}"
        )
    for folder in ("maps", "bots", "snapshots"):
        (RUNTIME / folder).mkdir(parents=True, exist_ok=True)
    sources = [BOOTSTRAP / "maps"]
    sources += [Path(maps_from)] if maps_from else [p / "Maps" for p in sc2_locations()]
    manifest = {}
    for source in sources:
        for map_file in source.rglob("*.SC2Map"):
            if "AIE" not in map_file.stem:
                continue
            target = RUNTIME / "maps" / map_file.name
            digest = hashlib.sha256(map_file.read_bytes()).hexdigest()
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"Map name collision with different contents: {target}")
            shutil.copy2(map_file, target)
            manifest[map_file.name] = {"source": str(map_file), "sha256": digest}
    write_json(RUNTIME / "maps-manifest.json", manifest)
    print(f"Bootstrap {revision}\nMaps: {RUNTIME / 'maps'} ({len(manifest)})")


def registry():
    bots = json.loads((HERE / "bots.json").read_text(encoding="utf-8"))
    local = HERE / "bots.local.json"
    if local.exists():
        bots.update(json.loads(local.read_text(encoding="utf-8")))
    return bots


def validate_name(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", name):
        raise ValueError("Use a simple bot/map name (letters, digits, dots, underscores, hyphens).")
    return name


def extract_zip(archive, destination):
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            normalized = entry.filename.replace("\\", "/")
            path = PurePosixPath(normalized)
            if (
                path.is_absolute()
                or ".." in path.parts
                or ":" in normalized
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise ValueError(f"Unsafe path in bot archive: {entry.filename}")
        bundle.extractall(destination)


def register_bot(name, source, race, bot_type):
    validate_name(name)
    if name in registry():
        raise ValueError(f"Bot already registered: {name}. Use a new name for a new version.")
    source = Path(source).resolve()
    destination = RUNTIME / "bots" / name
    if destination.exists():
        raise ValueError(f"Destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=RUNTIME) as temp:
        temp = Path(temp)
        if source.is_file() and zipfile.is_zipfile(source):
            extract_zip(source, temp)
            roots = list(temp.iterdir())
            bot_root = roots[0] if len(roots) == 1 and roots[0].is_dir() else temp
        elif source.is_dir():
            bot_root = source
        else:
            raise ValueError(
                "--source must be an extracted bot folder or a ZIP downloaded from AI Arena."
            )
        entrypoint = BOT_TYPES[bot_type].format(name=name)
        if not (bot_root / entrypoint).is_file():
            raise ValueError(
                f"Bot root must contain {entrypoint}; non-Python binaries must match --name."
            )
        shutil.copytree(bot_root, destination)
    path = HERE / "bots.local.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data[name] = {
        "id": f"local-{name}",
        "race": race,
        "type": bot_type,
        "source": destination.relative_to(HERE).as_posix(),
        "download": str(source),
    }
    write_json(path, data)
    print(f"Registered {name}: {destination}")


def snapshot_project():
    """Copy only bot/runtime inputs, never the Windows venv or bench outputs."""
    files = [
        ROOT / name
        for name in (
            "run.py",
            "ladder.py",
            "config.yml",
            "pyproject.toml",
            "poetry.lock",
            "README.md",
            "LICENSE",
        )
    ]
    files += list(ROOT.glob("*_builds.y*ml"))
    for folder in ("bot", "ares-sc2"):
        for path in (ROOT / folder).rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(ROOT / folder)
            if any(
                part
                in {
                    ".git",
                    ".venv",
                    "__pycache__",
                    ".pytest_cache",
                    "docs",
                    "tests",
                    "build",
                    "dist",
                    ".ruff_cache",
                }
                for part in relative.parts
            ):
                continue
            if path.suffix in {".pyc", ".pyd"} or "darwin.so" in path.name:
                continue
            files.append(path)
    files = sorted(set(files))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0" + path.read_bytes() + b"\0")
    fingerprint = digest.hexdigest()
    target = RUNTIME / "snapshots" / fingerprint / "BotBandido"
    if not (target.parent / "complete.json").exists():
        for path in files:
            out = target / path.relative_to(ROOT)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out)
        write_json(target.parent / "complete.json", {"sha256": fingerprint})
    return target, fingerprint


def mount(source, target, read_only=False):
    return {
        "type": "bind",
        "source": str(source.resolve()),
        "target": target,
        "read_only": read_only,
        "bind": {"create_host_path": False},
    }


def prepare_run(bot_name, opponent, map_name, max_game_time, max_real_time):
    bots = registry()
    for name in (bot_name, opponent):
        validate_name(name)
        if name not in bots:
            raise ValueError(f"Unknown bot {name}. Register it first; available: {', '.join(bots)}")
    if bot_name == opponent:
        raise ValueError("Use two distinct registered bot names.")
    map_name = map_name.removesuffix(".SC2Map")
    validate_name(map_name)
    map_file = RUNTIME / "maps" / f"{map_name}.SC2Map"
    if not map_file.is_file():
        raise ValueError(f"Map missing: {map_file}. Run --setup or --setup --maps-from DIR.")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = HERE / "runs" / f"{stamp}-{bot_name}-vs-{opponent}"
    run_dir.mkdir(parents=True)
    for folder in (
        "bots",
        "maps",
        "logs/bot_controller1",
        "logs/bot_controller2",
        "logs/sc2_controller",
        "replays",
    ):
        (run_dir / folder).mkdir(parents=True, exist_ok=True)
    shutil.copy2(map_file, run_dir / "maps" / map_file.name)
    manifest = {
        "status": "prepared",
        "bootstrap_commit": BOOTSTRAP_COMMIT,
        "expected_sc2_build": 75689,
        "sc2_image": SC2_IMAGE,
        "map": map_name,
        "map_sha256": hashlib.sha256(map_file.read_bytes()).hexdigest(),
        "players": [],
        "created_at": stamp,
    }
    overrides = {"services": {}}
    for number, name in enumerate((bot_name, opponent), 1):
        bot = dict(bots[name])
        project = bot["source"] == "project"
        if project:
            source, fingerprint = snapshot_project()
            bot["source_sha256"] = fingerprint
        else:
            source = HERE / bot["source"]
        if not (source / BOT_TYPES[bot["type"]].format(name=name)).is_file():
            raise ValueError(f"Missing bot entrypoint in {source}")
        shutil.copytree(source, run_dir / "bots" / name)
        (run_dir / "bots" / name / "data").mkdir(exist_ok=True)
        bot["name"] = name
        manifest["players"].append(bot)
        service = {
            "image": BOT_IMAGE,
            "platform": "linux/amd64",
            "volumes": [
                mount(run_dir / "bots", "/bots"),
                mount(run_dir / "logs" / f"bot_controller{number}", "/logs"),
            ],
        }
        if project:
            recipe_hash = hashlib.sha256((HERE / "Dockerfile.bot").read_bytes()).hexdigest()[:8]
            service.update(
                image=f"sc2bot-aiarena-local:{fingerprint[:16]}-{recipe_hash}",
                build={
                    "context": str(source),
                    "dockerfile": str(HERE / "Dockerfile.bot"),
                    "args": {"BOT_IMAGE": BOT_IMAGE},
                },
                environment={
                    "ACBOT_PYTHON": "/opt/sc2bot-venv/bin/python",
                    "PYTHONUNBUFFERED": "1",
                },
            )
        overrides["services"][f"bot_controller{number}"] = service
    config = (BOOTSTRAP / "config.toml").read_text(encoding="utf-8")
    for key, value in {
        "ROUNDS_PER_RUN": 1,
        "MAX_GAME_TIME": max_game_time,
        "MAX_REAL_TIME": max_real_time,
    }.items():
        config = re.sub(rf"(?m)^{key}\s*=.*$", f"{key} = {value}", config)
    (run_dir / "config.toml").write_text(config, encoding="utf-8")
    fields = []
    for bot in manifest["players"]:
        fields += [bot["id"], bot["name"], bot["race"], bot["type"]]
    (run_dir / "matches").write_text(",".join(fields + [map_name]) + "\n", encoding="utf-8")
    write_json(run_dir / "results.json", {"results": []})
    overrides["services"]["sc2_controller"] = {
        "image": SC2_IMAGE,
        "platform": "linux/amd64",
        "volumes": [
            mount(run_dir / "maps", "/root/StarCraftII/maps", True),
            mount(run_dir / "logs/sc2_controller", "/logs"),
        ],
    }
    overrides["services"]["proxy_controller"] = {
        "image": PROXY_IMAGE,
        "platform": "linux/amd64",
        "volumes": [
            mount(run_dir / "matches", "/app/matches"),
            mount(run_dir / "config.toml", "/app/config.toml", True),
            mount(run_dir / "results.json", "/app/results.json"),
            mount(run_dir / "replays", "/replays"),
            mount(run_dir / "logs", "/logs"),
        ],
    }
    write_json(run_dir / "compose.override.json", overrides)
    write_json(run_dir / "manifest.json", manifest)
    return run_dir, manifest


def verify_result(run_dir):
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))["results"]
    if len(results) != 1:
        raise RuntimeError(f"Expected exactly one result, found {len(results)}.")
    result = results[0]
    if result.get("type") not in NORMAL_RESULTS or result.get("game_steps", 0) <= 0:
        raise RuntimeError(f"Match did not complete normally: {result}")
    if not any(p.stat().st_size > 0 for p in (run_dir / "replays").rglob("*.SC2Replay")):
        raise RuntimeError("Controller returned a result without a replay.")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    for number, bot in enumerate(manifest["players"], 1):
        log = run_dir / "logs" / f"bot_controller{number}" / bot["name"] / "stderr.log"
        if not log.is_file():
            raise RuntimeError(f"Missing bot stdout/stderr log: {log}")
    return result


def run_match(args):
    run_dir, manifest = prepare_run(
        args.bot, args.opponent, args.map, args.max_game_time, args.max_real_time
    )
    print(f"Artifacts: {run_dir}", flush=True)
    if args.prepare_only:
        print("Inputs prepared; no game was played.")
        return 0
    compose = None
    try:
        docker = docker_ready()
        compose = [
            docker,
            "compose",
            "--project-name",
            f"sc2local-{run_dir.name[:22].lower()}",
            "--project-directory",
            str(BOOTSTRAP),
            "-f",
            str(BOOTSTRAP / "docker-compose.yml"),
            "-f",
            str(run_dir / "compose.override.json"),
        ]
        command(compose + ["config", "--format", "json"], log=run_dir / "compose-config.log")
        print("Pulling official images; see setup.log", flush=True)
        command(
            [docker, "pull", "--platform", "linux/amd64", SC2_IMAGE],
            timeout=3600,
            log=run_dir / "setup.log",
        )
        # Official v0 selects the newest Base* directory. Reject images with another build.
        command(
            [
                docker,
                "run",
                "--rm",
                "--platform",
                "linux/amd64",
                "--entrypoint",
                "sh",
                SC2_IMAGE,
                "-c",
                "test -x /root/StarCraftII/Versions/Base75689/SC2_x64 && "
                'test "$(ls -d /root/StarCraftII/Versions/Base* | sort -V | tail -1)" = '
                "/root/StarCraftII/Versions/Base75689",
            ],
            timeout=120,
            log=run_dir / "setup.log",
        )
        manifest["sc2_build_verified"] = 75689
        command(compose + ["pull", "--ignore-buildable"], timeout=3600, log=run_dir / "setup.log")
        command(compose + ["build"], timeout=3600, log=run_dir / "setup.log")
        resolved = json.loads(command(compose + ["config", "--format", "json"]))
        manifest["images"] = {}
        for service, config in resolved["services"].items():
            image_info = json.loads(command([docker, "image", "inspect", config["image"]]))[0]
            manifest["images"][service] = {
                "reference": config["image"],
                "id": image_info["Id"],
                "digests": image_info.get("RepoDigests", []),
            }
        manifest["status"] = "running"
        write_json(run_dir / "manifest.json", manifest)
        print("Starting local match; see compose.log", flush=True)
        # Do not use abort-on-container-exit: upstream stops other services before exiting itself.
        command(compose + ["up", "--detach", "--no-build"], log=run_dir / "compose.log")
        container = command(compose + ["ps", "--all", "--quiet", "proxy_controller"]).strip()
        if not container:
            raise RuntimeError("No proxy_controller container was created.")
        deadline = time.monotonic() + args.max_real_time + 240
        while True:
            state = json.loads(
                command([docker, "inspect", "--format", "{{json .State}}", container])
            )
            if not state["Running"]:
                if state["ExitCode"] != 0:
                    raise RuntimeError(f"Match controller exited {state['ExitCode']}.")
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Wall-clock timeout waiting for match controller.")
            time.sleep(2)
        manifest["result"] = verify_result(run_dir)
        manifest["status"] = "completed"
        print(json.dumps(manifest["result"]))
        return 0
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        manifest.update(status="failed", error=str(exc) or "Interrupted")
        print(f"Match NOT validated: {manifest['error']}", file=sys.stderr)
        return 2
    finally:
        if compose:
            for cmd, log in (
                (["logs", "--no-color", "--timestamps"], "compose.log"),
                (["images", "--format", "json"], "images.json.log"),
                (["down", "--timeout", "20"], "cleanup.log"),
            ):
                try:
                    command(compose + cmd, log=run_dir / log, timeout=90)
                except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
                    manifest.setdefault("cleanup_errors", []).append(str(exc))
        write_json(run_dir / "manifest.json", manifest)


def positive(value):
    value = int(value)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--setup", action="store_true", help="Download pinned bootstrap and copy AIE maps"
    )
    parser.add_argument("--maps-from", type=Path)
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--list-bots", action="store_true")
    parser.add_argument("--register", metavar="NAME")
    parser.add_argument("--source", type=Path, help="Downloaded ZIP or extracted bot folder")
    parser.add_argument("--race", choices=["T", "Z", "P", "R"])
    parser.add_argument("--type", choices=sorted(BOT_TYPES), default="python")
    parser.add_argument("--bot", default="BotBandido")
    parser.add_argument("--opponent")
    parser.add_argument("--map", default="PersephoneAIE_v4")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--max-game-time", type=positive, default=80640, help="SC2 game loops (22.4/s)"
    )
    parser.add_argument(
        "--max-real-time", type=positive, default=7200, help="Controller timeout in seconds"
    )
    args = parser.parse_args(argv)
    try:
        if args.setup:
            setup(args.maps_from)
        if args.register:
            if not args.source or not args.race:
                parser.error("--register requires --source and --race")
            register_bot(args.register, args.source, args.race, args.type)
        if args.list_bots:
            print(json.dumps(registry(), indent=2))
        if args.doctor:
            return doctor()
        if args.opponent:
            return run_match(args)
        if not (args.setup or args.register or args.list_bots):
            parser.print_help()
        return 0
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 2

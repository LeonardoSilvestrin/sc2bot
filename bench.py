"""Local benchmark: a fixed matrix of games against the built-in AI.

    bench.py run --out bench/<label> [--maps ...] [--races ...] [--armies ...]
                 [--games N] [--seed S]
    bench.py summarize bench/<label>
    bench.py compare bench/<baseline> bench/<challenger>

Each game runs in its own process, with a wall-clock timeout, and leaves
``<out>/<game_id>/`` with ``result.json``, ``replay.SC2Replay`` and
``log/game.jsonl``. ``summary.json`` is rewritten after every game.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for extra in ("ares-sc2/src/ares", "ares-sc2/src", "ares-sc2"):
    sys.path.append(str(ROOT / extra))

from harness import (  # noqa: E402
    GameSpec,
    build_record,
    identity,
    load_records,
    matrix,
    needs_replay,
    outcome_of,
    summarize,
)

DEFAULT_MAPS = ("PersephoneAIE_v4", "TorchesAIE_v4", "IncorporealAIE_v4")
DEFAULT_RACES = ("Zerg", "Terran", "Protoss")
CHILD_RESULT = "child.json"
REPLAY = "replay.SC2Replay"
LOG_DIRECTORY = "log"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="play the matrix")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--maps", nargs="+", default=list(DEFAULT_MAPS))
    run.add_argument("--races", nargs="+", default=list(DEFAULT_RACES))
    run.add_argument("--difficulties", nargs="+", default=["VeryHard"])
    run.add_argument("--ai-builds", nargs="+", default=["Macro"])
    run.add_argument(
        "--armies", nargs="+", default=None, help="army styles (default: the bot draws)"
    )
    run.add_argument("--games", type=int, default=1)
    run.add_argument("--seed", type=int, default=1)
    run.add_argument("--time-limit", type=float, default=1800.0, help="game seconds")
    run.add_argument("--wall-timeout", type=float, default=3600.0, help="real seconds")
    run.add_argument("--only", type=int, nargs="*", help="play only these matrix indices")

    play = commands.add_parser("play", help="(internal) play one game")
    play.add_argument("--spec", type=Path, required=True)
    play.add_argument("--directory", type=Path, required=True)

    summary = commands.add_parser("summarize", help="summarize a run")
    summary.add_argument("directory", type=Path)

    compare = commands.add_parser("compare", help="baseline against challenger")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("challenger", type=Path)

    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "play":
        return _play(args.spec, args.directory)
    if args.command == "summarize":
        print(json.dumps(summarize(load_records(args.directory)), indent=2))
        return 0
    return _compare(args.baseline, args.challenger)


def _run(args) -> int:
    specs = matrix(
        maps=args.maps,
        races=args.races,
        difficulties=args.difficulties,
        ai_builds=args.ai_builds,
        games=args.games,
        seed=args.seed,
        game_time_limit=args.time_limit,
        armies=args.armies or (None,),
    )
    out: Path = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    label = out.name
    build = identity()
    (out / "matrix.json").write_text(
        json.dumps({"build": build, "games": [spec.to_json() for spec in specs]}, indent=2),
        encoding="utf-8",
    )
    for spec in specs:
        if args.only is not None and spec.index not in args.only:
            continue
        directory = out / spec.game_id
        previous = _read_json(directory / "result.json")
        if previous is not None:
            # A game the bot never played is not a played cell of the matrix.
            if not needs_replay(previous):
                print(f"{spec.game_id}: already played")
                continue
            print(f"{spec.game_id}: {outcome_of(previous)} before; playing again")
        directory.mkdir(parents=True, exist_ok=True)
        spec_path = directory / "spec.json"
        spec_path.write_text(json.dumps(spec.to_json(), indent=2), encoding="utf-8")
        started = time.monotonic()
        timed_out = False
        exit_code: int | None
        with (directory / "stdout.txt").open("w", encoding="utf-8") as output:
            try:
                exit_code = subprocess.run(
                    [
                        sys.executable,
                        __file__,
                        "play",
                        "--spec",
                        str(spec_path),
                        "--directory",
                        str(directory),
                    ],
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    cwd=ROOT,
                    timeout=args.wall_timeout,
                    check=False,
                ).returncode
            except subprocess.TimeoutExpired:
                timed_out, exit_code = True, None
        child = _read_json(directory / CHILD_RESULT) or {}
        record = build_record(
            spec,
            label=label,
            identity=build,
            result=child.get("result"),
            game_time=child.get("game_time"),
            exit_code=exit_code,
            wall_timed_out=timed_out,
            wall_seconds=time.monotonic() - started,
            replay=directory / REPLAY,
            log=directory / LOG_DIRECTORY / "game.jsonl",
            error=child.get("error"),
        )
        (directory / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(f"{spec.game_id}: {record['outcome']} at {record['game_time']}")
        (out / "summary.json").write_text(
            json.dumps(summarize(load_records(out)), indent=2), encoding="utf-8"
        )
    return 0


def _play(spec_path: Path, directory: Path) -> int:
    from sc2 import maps
    from sc2.data import AIBuild, Difficulty, Race
    from sc2.main import run_game
    from sc2.player import Bot, Computer

    from bot.logs import JsonlLogger, Logs
    from bot.main import MyBot

    spec = GameSpec.from_json(_read_json(spec_path))
    child: dict = {"result": None, "game_time": None, "error": None}
    bot = MyBot(
        logs=Logs(JsonlLogger(directory, session_name=LOG_DIRECTORY)), army=spec.army
    )
    exit_code = 0
    try:
        result = run_game(
            maps.get(spec.map_name),
            [
                Bot(Race.Terran, bot, "MyBot"),
                Computer(
                    Race[spec.enemy_race],
                    Difficulty[spec.difficulty],
                    ai_build=AIBuild[spec.ai_build],
                ),
            ],
            realtime=False,
            save_replay_as=str(directory / REPLAY),
            game_time_limit=spec.game_time_limit,
            random_seed=spec.seed,
        )
        child["result"] = None if result is None else str(result)
    except Exception:  # the record must say why, whatever it was
        child["error"] = traceback.format_exc()
        exit_code = 1
    try:
        child["game_time"] = float(bot.time)
    except Exception:  # the game may never have started
        child["game_time"] = None
    (directory / CHILD_RESULT).write_text(json.dumps(child, indent=2), encoding="utf-8")
    return exit_code


def _compare(baseline: Path, challenger: Path) -> int:
    before, after = load_records(baseline), load_records(challenger)
    specs_before = [record["spec"] for record in before]
    specs_after = [record["spec"] for record in after]
    if specs_before != specs_after:
        print("the two runs did not play the same matrix", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"baseline": summarize(before), "challenger": summarize(after)},
            indent=2,
        )
    )
    return 0


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


if __name__ == "__main__":
    sys.exit(main())

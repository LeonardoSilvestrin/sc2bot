import argparse
import platform
import random
import sys
from os import path
from pathlib import Path

from loguru import logger
from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")

import yaml

from bot.ego.planners.economy.knowledge.styles import STYLES
from bot.logs import ChatConfig, JsonlLogger, Logs, OverlayConfig, SnapshotConfig
from bot.main import MyBot
from harness import AI_BUILDS, DEFAULT_LAUNCHER, RACES, WIDE, WIDE_MAPS, Game
from ladder import run_ladder_game

plt = platform.system()
# change if non default setup / linux
# if having issues with this, modify `map_list` below manually
if plt == "Windows":
    MAPS_PATH: str = "C:\\Program Files (x86)\\StarCraft II\\Maps"
elif plt == "Darwin":
    MAPS_PATH: str = "/Applications/StarCraft II/Maps"
elif plt == "Linux":
    # path would look a bit like this on linux after installing
    # SC2 via lutris
    MAPS_PATH: str = "~/<username>/Games/battlenet/drive_c/Program Files (x86)/StarCraft II/Maps"
else:
    logger.error(f"{plt} not supported")
    sys.exit()

CONFIG_FILE: str = "config.yml"
MAP_FILE_EXT: str = "SC2Map"
MY_BOT_NAME: str = "MyBotName"
MY_BOT_RACE: str = "MyBotRace"
# Gap between markers drawn by --spatial-view; presentation only.
DEFAULT_SPATIAL_VIEW_SPACING = 4
# How many games each --matrix plays, and what varies in them.
SINGLE, BUILDS, WIDE_MATRIX = "single", "builds", "wide"
# A game of a sweep that goes this long is called off, so one stuck game does
# not eat the rest of the afternoon. A single game is not capped.
SWEEP_TIME_LIMIT = 1800.0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_local_args(args=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--bot-log",
        choices=("off", "events"),
        default="off",
        help="Write the structured event log to logs/game-<time>/game.jsonl.",
    )
    parser.add_argument(
        "--spatial-view",
        action="store_true",
        help="Draw the influence field and decisions in the game window.",
    )
    parser.add_argument(
        "--spatial-view-spacing",
        type=_positive_int,
        default=DEFAULT_SPATIAL_VIEW_SPACING,
        metavar="UNITS",
        help="Approximate gap between drawn markers (default: %(default)s).",
    )
    parser.add_argument(
        "--spatial-snapshot",
        action="store_true",
        help="Write an SVG field snapshot every interval and on objective changes.",
    )
    parser.add_argument(
        "--spatial-snapshot-interval",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="Game seconds between SVG snapshots (default: %(default)s).",
    )
    parser.add_argument(
        "--no-chat",
        action="store_true",
        help="Do not say anything in the game chat.",
    )
    parser.add_argument(
        "--army",
        choices=sorted(STYLES),
        default=None,
        help="Army style to play (default: drawn for the enemy's race).",
    )
    parser.add_argument(
        "--enemy-race",
        choices=("Zerg", "Terran", "Protoss", "Random"),
        default=None,
        help="Race of the built-in AI (default: random).",
    )
    parser.add_argument(
        "--difficulty",
        choices=[difficulty.name for difficulty in Difficulty],
        default="CheatInsane",
        help="Difficulty of the built-in AI (default: %(default)s).",
    )
    parser.add_argument(
        "--ai-build",
        choices=[build.name for build in AIBuild],
        default="Rush",
        help="Build of the built-in AI (default: %(default)s); --matrix picks its own.",
    )
    parser.add_argument(
        "--matrix",
        choices=(SINGLE, BUILDS, WIDE_MATRIX),
        default=DEFAULT_LAUNCHER,
        help=(
            f"single: one game. builds: {len(AI_BUILDS)} games, one per way "
            f"the AI opens ({', '.join(AI_BUILDS)}), same map and race. "
            f"wide: {len(WIDE)} games, the whole matrix of harness/matrix.py. "
            "Nothing is recorded: use bench.py to measure. "
            "Default: %(default)s, from harness/matrix.py."
        ),
    )
    parser.add_argument(
        "--time-limit",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Game seconds before a game is called off "
            f"(default: none for --matrix {SINGLE}, {SWEEP_TIME_LIMIT:.0f} otherwise)."
        ),
    )
    local_args, _ = parser.parse_known_args(args)
    return local_args


def build_logs(local_args, *, is_ladder: bool) -> Logs:
    if is_ladder:
        return Logs()
    chat = ChatConfig(enabled=not local_args.no_chat)
    snapshots = local_args.spatial_snapshot
    logger_ = JsonlLogger(Path("logs")) if local_args.bot_log == "events" or snapshots else None
    if logger_ is not None:
        print(f"Bot structured log: {logger_.path}")
    return Logs(
        logger_,
        overlay=OverlayConfig(
            enabled=local_args.spatial_view,
            draw_spacing=float(local_args.spatial_view_spacing),
        ),
        snapshots=SnapshotConfig(
            enabled=snapshots, interval_seconds=local_args.spatial_snapshot_interval
        ),
        snapshot_directory=None if logger_ is None else logger_.session_directory / "spatial",
        chat=chat,
    )


def local_games(local_args, map_list: list[str]) -> list[Game]:
    """The games this run plays, in order: (map, enemy race, AI build).

    `single` keeps the launcher as it was -- one game, on a map drawn from the
    ones installed. `builds` holds the map and the race and varies only how the
    AI opens, which is the comparison worth watching by eye. `wide` walks the
    whole matrix `bench.py` measures.
    """

    if local_args.matrix == WIDE_MATRIX:
        for name in WIDE_MAPS:
            if name not in map_list:
                print(f"{name} is not installed; skipping its games")
        return [game for game in WIDE if game.map_name in map_list]
    map_name = random.choice(map_list)
    race = local_args.enemy_race or random.choice(list(RACES))
    if local_args.matrix == BUILDS:
        return [Game(map_name, race, ai_build) for ai_build in AI_BUILDS]
    return [Game(map_name, race, local_args.ai_build)]


def time_limit(local_args) -> float | None:
    """What is asked for, else: a sweep caps each game so one stuck game does
    not eat the rest of it; a single game runs as long as it takes."""

    if local_args.time_limit is not None:
        return local_args.time_limit
    return None if local_args.matrix == SINGLE else SWEEP_TIME_LIMIT


def main():
    local_args = parse_local_args()

    bot_name: str = "MyBot"
    race: Race = Race.Random

    __user_config_location__: str = path.abspath(".")
    user_config_path: str = path.join(__user_config_location__, CONFIG_FILE)
    # attempt to get race and bot name from config file if they exist
    if path.isfile(user_config_path):
        with open(user_config_path) as config_file:
            config: dict = yaml.safe_load(config_file)
            if MY_BOT_NAME in config:
                bot_name = config[MY_BOT_NAME]
            if MY_BOT_RACE in config:
                race = Race[config[MY_BOT_RACE].title()]

    is_ladder = "--LadderServer" in sys.argv
    army = None if is_ladder else local_args.army

    def our_bot() -> Bot:
        # A bot that played a game cannot play the next one.
        return Bot(
            race, MyBot(logs=build_logs(local_args, is_ladder=is_ladder), army=army), bot_name
        )

    if is_ladder:
        # Ladder game started by LadderManager
        print("Starting ladder game...")
        result, opponentid = run_ladder_game(our_bot())
        print(result, " against opponent ", opponentid)
    else:
        # Local game
        map_list: list[str] = [
            p.name.replace(f".{MAP_FILE_EXT}", "")
            for p in Path(MAPS_PATH).glob(f"*.{MAP_FILE_EXT}")
            if p.is_file()
        ]
        if len(map_list) == 0:
            logger.error("Can't find maps, please check `MAPS_PATH` in `run.py'")
            logger.info("Trying back up option")
            logger.info(
                f"\nLooking for maps in {MAPS_PATH} but didn't find anything. \n"
                f"If this path is correct please ensure maps are present. \n"
                f"If this path is incorrect please edit the `MAPS_PATH` in `run.py` \n"
                f"Tip: If you're using linux, MAPS_PATH will definitely need updating\n"
            )

            # see if user has any recent ladder maps
            map_list = [
                "PylonAIE_v4",
                "PersephoneAIE_v4",
                "TorchesAIE_v4",
                "IncorporealAIE_v4",
                "MagannathaAIE_v2",
                "UltraloveAIE_v2",
            ]

        games = local_games(local_args, map_list)
        limit = time_limit(local_args)
        if len(games) > 1:
            print(f"Starting {len(games)} local games ({local_args.matrix})...")
        for number, (map_name, enemy_race, ai_build) in enumerate(games, start=1):
            if len(games) > 1:
                print(f"game {number}/{len(games)}: {map_name} vs {enemy_race} ({ai_build})")
            else:
                print("Starting local game...")
            result = run_game(
                maps.get(map_name),
                [
                    our_bot(),
                    Computer(
                        Race[enemy_race],
                        Difficulty[local_args.difficulty],
                        ai_build=AIBuild[ai_build],
                    ),
                ],
                realtime=False,
                game_time_limit=limit,
            )
            if len(games) > 1:
                print(f"game {number}/{len(games)}: {result}")


# Start game
if __name__ == "__main__":
    main()

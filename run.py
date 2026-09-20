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
        help="Build of the built-in AI (default: %(default)s).",
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
    bot1 = Bot(
        race, MyBot(logs=build_logs(local_args, is_ladder=is_ladder), army=army), bot_name
    )

    if is_ladder:
        # Ladder game started by LadderManager
        print("Starting ladder game...")
        result, opponentid = run_ladder_game(bot1)
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

        if local_args.enemy_race is None:
            enemy_race = random.choice([Race.Zerg, Race.Terran, Race.Protoss])
        else:
            enemy_race = Race[local_args.enemy_race]
        print("Starting local game...")
        run_game(
            maps.get(random.choice(map_list)),
            [
                bot1,
                Computer(
                    enemy_race,
                    Difficulty[local_args.difficulty],
                    ai_build=AIBuild[local_args.ai_build],
                ),
            ],
            realtime=False,
        )


# Start game
if __name__ == "__main__":
    main()

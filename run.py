#run.py
import random
import sys
from os import path
from pathlib import Path
import platform
from typing import List
from loguru import logger

from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

sys.path.append("ares-sc2/src/ares")
sys.path.append("ares-sc2/src")
sys.path.append("ares-sc2")

import yaml

from bot.main import MyBot
from ladder import run_ladder_game

plt = platform.system()
if plt == "Windows":
    MAPS_PATH: str = "C:\\Program Files (x86)\\StarCraft II\\Maps"
elif plt == "Darwin":
    MAPS_PATH: str = "/Applications/StarCraft II/Maps"
elif plt == "Linux":
    MAPS_PATH: str = (
        "~/<username>/Games/battlenet/drive_c/Program Files (x86)/StarCraft II/Maps"
    )
else:
    logger.error(f"{plt} not supported")
    sys.exit()

CONFIG_FILE: str = "config.yml"
MAP_FILE_EXT: str = "SC2Map"
MY_BOT_NAME: str = "MyBotName"
MY_BOT_RACE: str = "MyBotRace"


def main():
    bot_name: str = "MyBot"

    # ✅ não deixe Random aqui, sua build order é Terran
    race: Race = Race.Terran

    __user_config_location__: str = path.abspath(".")
    user_config_path: str = path.join(__user_config_location__, CONFIG_FILE)

    # opcional: permitir override por config.yml, mas valida
    if path.isfile(user_config_path):
        with open(user_config_path) as config_file:
            config: dict = yaml.safe_load(config_file) or {}
            if MY_BOT_NAME in config:
                bot_name = config[MY_BOT_NAME]
            if MY_BOT_RACE in config:
                cfg_race = str(config[MY_BOT_RACE]).title()
                try:
                    race = Race[cfg_race]
                except Exception:
                    logger.warning(f"Invalid {MY_BOT_RACE}='{cfg_race}', forcing Terran.")
                    race = Race.Terran

    # ✅ se alguém colocar Random no config, ainda assim trava tudo.
    # então aqui eu garanto Terran:
    race = Race.Terran

    bot1 = Bot(race, MyBot(), bot_name)

    if "--LadderServer" in sys.argv:
        print("Starting ladder game...")
        result, opponentid = run_ladder_game(bot1)
        print(result, " against opponent ", opponentid)
    else:
        map_list: List[str] = [
            p.name.replace(f".{MAP_FILE_EXT}", "")
            for p in Path(MAPS_PATH).glob(f"*.{MAP_FILE_EXT}")
            if p.is_file()
        ]
        if len(map_list) == 0:
            logger.error(f"Can't find maps, please check `MAPS_PATH` in `run.py'")
            logger.info("Trying back up option")
            map_list = [
                "PylonAIE_v4",
                "PersephoneAIE_v4",
                "TorchesAIE_v4",
                "IncorporealAIE_v4",
                "MagannathaAIE_v2",
                "UltraloveAIE_v2",
            ]

        random_race = random.choice([Race.Zerg, Race.Terran, Race.Protoss])
        print("Starting local game...")
        run_game(
            maps.get(random.choice(map_list)),
            [
                bot1,
                Computer(random_race, Difficulty.CheatVision, ai_build=AIBuild.Macro),
            ],
            realtime=False,
        )


if __name__ == "__main__":
    main()
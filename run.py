from __future__ import annotations

import argparse

from sc2 import maps
from sc2.main import run_game
from sc2.player import Bot, Computer
from sc2.data import Race, Difficulty

from bot.terran_bot import TerranBot


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--strat", default="default", help="Nome do JSON em bot/strats/<name>.json")
    p.add_argument("--map", dest="map_name", default="AbyssalReefLE")
    p.add_argument("--realtime", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    bot = TerranBot(strat_name=args.strat, debug=True)

    run_game(
        maps.get(args.map_name),
        [Bot(Race.Terran, bot), Computer(Race.Zerg, Difficulty.Medium)],
        realtime=args.realtime,
    )


if __name__ == "__main__":
    main()

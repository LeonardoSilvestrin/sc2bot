# bot/main.py
from __future__ import annotations

from typing import Optional

from ares import AresBot
from sc2.data import Result

from bot.ares_wrapper import AresWrapper
from bot.devlog import DevLogger
from bot.mind.self import RuntimeApp


class MyBot(AresBot):
    def __init__(self, game_step_override: Optional[int] = None, *, debug: bool = True):
        super().__init__(game_step_override)
        self.debug = debug

        # logger pode ficar aqui (infra), mas runtime decide como usar
        self.log = DevLogger(enabled=True)

        # wrapper do engine (opcional ficar aqui; pode migrar pro runtime depois)
        self.ares = AresWrapper(self)

        # runtime é a única "inteligência" conectada ao main
        self.rt = RuntimeApp.build(log=self.log, debug=debug)

    async def on_start(self) -> None:
        await super().on_start()
        await self.rt.on_start(self)

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        await self.rt.on_step(self, iteration=iteration)

    async def on_end(self, game_result: Result) -> None:
        await super().on_end(game_result)
        await self.rt.on_end(self, game_result=game_result)
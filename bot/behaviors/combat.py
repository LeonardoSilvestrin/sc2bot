from __future__ import annotations


class CombatBehavior:
    def __init__(self, bot, state, debug: bool = True):
        self.bot = bot
        self.state = state
        self.debug = debug

    async def step(self):
        return

from __future__ import annotations


class Builder:
    def __init__(self, bot, economy, placement, state):
        self.bot = bot
        self.economy = economy
        self.placement = placement
        self.state = state

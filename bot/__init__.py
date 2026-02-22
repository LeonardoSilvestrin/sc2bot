# __init__.py
from __future__ import annotations

from sc2.data import Race

from .terran_bot import TerranBot


class CompetitiveBot(TerranBot):
    NAME = "Boi Bandido"
    RACE = Race.Terran

    # Estratégia fixa do build (não de CLI)
    STRATEGY = "default"

    def __init__(self, *, debug: bool = True):
        super().__init__(strat_name=self.STRATEGY, debug=debug)
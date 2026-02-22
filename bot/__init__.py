from sc2.data import Race
from .terran_bot import TerranBot

class CompetitiveBot(TerranBot):
    NAME = "MyBot"
    RACE = Race.Terran
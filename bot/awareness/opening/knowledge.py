"""What a standard opening looks like, by race.

Every number here is a ladder norm, in seconds of game time: when a natural is
early and when it is late, how much production and gas a standard opening has
by when, which structures belong in a main and which ones only a rush builds.
The belief reads these and nothing else about races, so calibrating the read
of an opening means editing this table -- not the scoring.

A Random opponent whose race no unit has given away yet reads `UNKNOWN`: the
middle of the three, and no expectation about what stands in the main, so a
main we cannot interpret never accuses anyone of a proxy.
"""

from __future__ import annotations

from dataclasses import dataclass

from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId


@dataclass(frozen=True, slots=True)
class OpeningExpectations:
    race: Race
    # A natural standing by `natural_early` is greedy; one still missing at
    # `natural_late` bought something else with the money.
    natural_early: float
    natural_late: float
    third_early: float
    third_late: float
    # Army production, how many a standard opening has, and by when.
    production: frozenset[UnitTypeId]
    standard_production: float
    production_by: float
    # Production counted this long after `production_by` still reads as an
    # opening; later it is just a normal mid game.
    production_window: float
    # What belongs in the main: missing from a well-scouted main, it is
    # somewhere else.
    expected_in_main: frozenset[UnitTypeId]
    expected_in_main_by: float
    # Each tech structure type seen is a step up the tree.
    tech: frozenset[UnitTypeId]
    # Gas, how much a standard opening has, and by when.
    standard_gases: float
    gas_by: float
    # Structures nobody builds this early without an attack behind them.
    rush: frozenset[UnitTypeId]
    rush_by: float


ZERG = OpeningExpectations(
    race=Race.Zerg,
    # Hatch first lands around 1:00; a pool-first natural comes after 1:45.
    natural_early=55.0,
    natural_late=115.0,
    third_early=160.0,
    third_late=270.0,
    production=frozenset(
        {UnitTypeId.SPAWNINGPOOL, UnitTypeId.ROACHWARREN, UnitTypeId.BANELINGNEST}
    ),
    standard_production=1.0,
    production_by=110.0,
    production_window=120.0,
    expected_in_main=frozenset({UnitTypeId.SPAWNINGPOOL}),
    expected_in_main_by=130.0,
    tech=frozenset(
        {
            UnitTypeId.LAIR,
            UnitTypeId.HIVE,
            UnitTypeId.ROACHWARREN,
            UnitTypeId.BANELINGNEST,
            UnitTypeId.SPIRE,
            UnitTypeId.GREATERSPIRE,
            UnitTypeId.HYDRALISKDEN,
            UnitTypeId.LURKERDENMP,
            UnitTypeId.INFESTATIONPIT,
            UnitTypeId.NYDUSNETWORK,
            UnitTypeId.ULTRALISKCAVERN,
        }
    ),
    standard_gases=1.0,
    gas_by=150.0,
    rush=frozenset({UnitTypeId.SPINECRAWLER}),
    rush_by=150.0,
)

PROTOSS = OpeningExpectations(
    race=Race.Protoss,
    # Nexus first lands around 1:30; a gateway expand lands after 2:30.
    natural_early=85.0,
    natural_late=170.0,
    third_early=230.0,
    third_late=340.0,
    production=frozenset({UnitTypeId.GATEWAY, UnitTypeId.WARPGATE}),
    standard_production=1.0,
    production_by=100.0,
    production_window=120.0,
    expected_in_main=frozenset({UnitTypeId.GATEWAY}),
    expected_in_main_by=120.0,
    tech=frozenset(
        {
            UnitTypeId.CYBERNETICSCORE,
            UnitTypeId.TWILIGHTCOUNCIL,
            UnitTypeId.ROBOTICSFACILITY,
            UnitTypeId.STARGATE,
            UnitTypeId.DARKSHRINE,
            UnitTypeId.TEMPLARARCHIVE,
            UnitTypeId.ROBOTICSBAY,
            UnitTypeId.FLEETBEACON,
        }
    ),
    standard_gases=1.0,
    gas_by=150.0,
    # A Forge before the Cybernetics Core is a cannon opening, not economy.
    rush=frozenset({UnitTypeId.FORGE, UnitTypeId.PHOTONCANNON}),
    rush_by=140.0,
)

TERRAN = OpeningExpectations(
    race=Race.Terran,
    # A CC first lands around 1:35; a reaper or 2-rax natural comes after 2:30.
    natural_early=95.0,
    natural_late=185.0,
    third_early=250.0,
    third_late=360.0,
    production=frozenset({UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT}),
    standard_production=1.0,
    production_by=105.0,
    production_window=120.0,
    expected_in_main=frozenset({UnitTypeId.BARRACKS}),
    expected_in_main_by=115.0,
    tech=frozenset(
        {
            UnitTypeId.FACTORY,
            UnitTypeId.STARPORT,
            UnitTypeId.ARMORY,
            UnitTypeId.GHOSTACADEMY,
            UnitTypeId.FUSIONCORE,
            UnitTypeId.BARRACKSTECHLAB,
            UnitTypeId.FACTORYTECHLAB,
            UnitTypeId.STARPORTTECHLAB,
        }
    ),
    standard_gases=1.0,
    gas_by=160.0,
    rush=frozenset({UnitTypeId.BUNKER}),
    rush_by=170.0,
)

UNKNOWN = OpeningExpectations(
    race=Race.Random,
    natural_early=80.0,
    natural_late=160.0,
    third_early=215.0,
    third_late=325.0,
    production=ZERG.production | PROTOSS.production | TERRAN.production,
    standard_production=1.0,
    production_by=105.0,
    production_window=120.0,
    # Nothing is expected of a main whose race we do not know.
    expected_in_main=frozenset(),
    expected_in_main_by=120.0,
    tech=ZERG.tech | PROTOSS.tech | TERRAN.tech,
    standard_gases=1.0,
    gas_by=155.0,
    rush=ZERG.rush | PROTOSS.rush | TERRAN.rush,
    rush_by=150.0,
)

BY_RACE: dict[Race, OpeningExpectations] = {
    Race.Zerg: ZERG,
    Race.Protoss: PROTOSS,
    Race.Terran: TERRAN,
}


def expectations_for(race: Race) -> OpeningExpectations:
    """What a standard opening of that race looks like; `UNKNOWN` until the
    race is known."""

    return BY_RACE.get(race, UNKNOWN)

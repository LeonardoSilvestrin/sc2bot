"""Carry out Intel's Sensor Tower construction plan."""

from __future__ import annotations

from dataclasses import dataclass

from ares.behaviors.macro import BuildStructure
from sc2.ids.unit_typeid import UnitTypeId

from bot.ego.planners import SensorTowerPlan

SENSOR_TOWER_MINERAL_COST = 125
SENSOR_TOWER_VESPENE_COST = 100


@dataclass(frozen=True, slots=True)
class SensorTowerReport:
    # Structures handed to Ares to build this frame.
    building: tuple[str, ...] = ()


def execute(bot, plan: SensorTowerPlan) -> SensorTowerReport:
    building: list[str] = []
    if (
        plan.sites
        and not plan.engineering_bay
        and bot.minerals >= SENSOR_TOWER_MINERAL_COST
        and bot.vespene >= SENSOR_TOWER_VESPENE_COST
    ):
        site = plan.sites[0]
        bot.register_behavior(
            BuildStructure(
                site.base,
                UnitTypeId.SENSORTOWER,
                closest_to=site.target,
                sensor_tower=True,
                production=False,
                find_alternative=False,
            )
        )
        building.append(UnitTypeId.SENSORTOWER.name)
    return SensorTowerReport(tuple(building))

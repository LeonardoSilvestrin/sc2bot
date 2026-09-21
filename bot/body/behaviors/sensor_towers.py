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


class BuildSensorTower(BuildStructure):
    """Build only at the point whose radar coverage the planner evaluated.

    Ares' sensor_tower flag prefers preset tower spots over closest_to. Even
    without that flag, an occupied target can fall back to a different spot.
    Preview without reserving and reject that fallback before sending a worker.
    """

    def execute(self, ai, config, mediator) -> bool:
        placement = mediator.request_building_placement(
            base_location=self.base_location,
            structure_type=self.structure_id,
            closest_to=self.closest_to,
            production=False,
            find_alternative=False,
            reserve_placement=False,
        )
        if placement is None or placement != self.closest_to:
            return False
        return super().execute(ai, config, mediator)


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
            BuildSensorTower(
                site.base,
                UnitTypeId.SENSORTOWER,
                closest_to=site.target,
                production=False,
                find_alternative=False,
            )
        )
        building.append(UnitTypeId.SENSORTOWER.name)
    return SensorTowerReport(tuple(building))

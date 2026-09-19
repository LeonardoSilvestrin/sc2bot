"""Detection: carries out the detection plan.

The scan comes from the ready Orbital Command with the most energy (lowest tag
on a tie). Each base that needs a Missile Turret gets one through Ares'
BuildStructure at the expansion location nearest that base, without looking
at other bases; Ares sends one builder at a time. An Engineering Bay goes
first when there is none.
"""

from __future__ import annotations

from dataclasses import dataclass

from ares.behaviors.macro import BuildStructure
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from bot.ego.planners import DetectionPlan
from bot.ego.planners.intel.detection import SCAN_ENERGY

TURRET_COST = 100
ENGINEERING_BAY_COST = 125


@dataclass(frozen=True, slots=True)
class DetectionReport:
    # The Orbital that scanned, by tag; None when nothing did.
    scanned_by: int | None = None
    # Structures handed to Ares to build this frame.
    building: tuple[str, ...] = ()


def execute(bot, plan: DetectionPlan) -> DetectionReport:
    scanned_by = None
    if plan.scan is not None:
        orbitals = [
            structure
            for structure in bot.structures
            if structure.type_id is UnitTypeId.ORBITALCOMMAND
            and structure.is_ready
            and structure.energy >= SCAN_ENERGY
        ]
        if orbitals:
            orbital = max(orbitals, key=lambda unit: (unit.energy, -unit.tag))
            orbital(AbilityId.SCANNERSWEEP_SCAN, plan.scan)
            scanned_by = orbital.tag
    building: list[str] = []
    if plan.engineering_bay and bot.minerals >= ENGINEERING_BAY_COST:
        bot.register_behavior(
            BuildStructure(bot.start_location, UnitTypeId.ENGINEERINGBAY, to_count=1)
        )
        building.append(UnitTypeId.ENGINEERINGBAY.name)
    elif plan.turrets and bot.minerals >= TURRET_COST:
        base = plan.turrets[0]
        location = min(
            bot.expansion_locations_list,
            key=lambda point: (point.distance_to(base), point.x, point.y),
            default=base,
        )
        bot.register_behavior(
            BuildStructure(
                location,
                UnitTypeId.MISSILETURRET,
                closest_to=base,
                missile_turret=True,
                find_alternative=False,
            )
        )
        building.append(UnitTypeId.MISSILETURRET.name)
    return DetectionReport(scanned_by=scanned_by, building=tuple(building))

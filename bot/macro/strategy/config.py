from dataclasses import dataclass, field

from bot.engine.economy.models import ResourceCost
from bot.world.awareness import MacroPosture

from .goals import MacroGoalSet
from .profiles import bio_three_one_one
from .reference_build import (
    ReferenceBuild,
    bio_three_one_one_reference,
)


@dataclass(frozen=True, slots=True)
class ResourceOverflowConfig:
    """Bank-size pressure that raises what we want to *own*.

    A pile above ``*_threshold`` means we are failing to convert income into
    value; it is evidence of a problem, not a diagnosis of too little
    production. So it raises the army we want (``army_supply_bonus``) and is
    only allowed to raise the number of producers (``production_bonus``)
    once the existing ones are demonstrably saturated -- adding buildings
    next to idle buildings would convert nothing. See
    ``production.army_demand`` and ``construction.capacity.assess_capacity``.
    """

    mineral_threshold: float = 800.0
    mineral_step: float = 400.0
    vespene_threshold: float = 400.0
    vespene_step: float = 200.0
    army_supply_per_step: float = 8.0

    def __post_init__(self) -> None:
        if self.mineral_threshold < 0.0 or self.vespene_threshold < 0.0:
            raise ValueError("overflow thresholds must not be negative")
        if self.mineral_step <= 0.0 or self.vespene_step <= 0.0:
            raise ValueError("overflow steps must be positive")
        if self.army_supply_per_step < 0.0:
            raise ValueError("army_supply_per_step must not be negative")

    def production_bonus(self, *, minerals: float, vespene: float) -> int:
        """Extra production structures justified by the current bank size."""

        return max(
            self._steps_over(minerals, self.mineral_threshold, self.mineral_step),
            self._steps_over(vespene, self.vespene_threshold, self.vespene_step),
        )

    def army_supply_bonus(self, *, minerals: float, vespene: float) -> float:
        """Extra army-supply headroom justified by the current bank size."""

        return self.production_bonus(
            minerals=minerals, vespene=vespene
        ) * self.army_supply_per_step

    @staticmethod
    def _steps_over(amount: float, threshold: float, step: float) -> int:
        if amount <= threshold:
            return 0
        return 1 + int((amount - threshold) // step)


@dataclass(frozen=True, slots=True)
class MacroPlannerConfig:
    """Costs and thresholds used to turn a strategy into spend proposals."""

    goals: MacroGoalSet = field(default_factory=bio_three_one_one)
    reference_build: ReferenceBuild | None = field(
        default_factory=bio_three_one_one_reference
    )
    overflow: ResourceOverflowConfig = field(default_factory=ResourceOverflowConfig)
    worker_cost: ResourceCost = field(
        default_factory=lambda: ResourceCost(minerals=50, supply=1.0)
    )
    supply_cost: ResourceCost = field(
        default_factory=lambda: ResourceCost(minerals=100)
    )
    expansion_cost: ResourceCost = field(
        default_factory=lambda: ResourceCost(minerals=400)
    )
    gas_cost: ResourceCost = field(
        default_factory=lambda: ResourceCost(minerals=75)
    )
    supply_buffer: float = 6.0
    max_supply_cap: float = 200.0
    worker_priority: int = 66
    supply_priority: int = 96
    expansion_priority: int = 58
    gas_priority: int = 61
    army_priority: int = 70
    production_priority: int = 64
    addon_priority: int = 67
    upgrade_priority: int = 63

    def __post_init__(self) -> None:
        if self.supply_buffer < 0.0 or self.max_supply_cap <= 0.0:
            raise ValueError("invalid supply settings")
        for priority in (
            self.worker_priority,
            self.supply_priority,
            self.expansion_priority,
            self.gas_priority,
            self.army_priority,
            self.production_priority,
            self.addon_priority,
            self.upgrade_priority,
        ):
            if not 0 <= priority <= 100:
                raise ValueError("priorities must be between 0 and 100")

    def priority_for(
        self,
        category: str,
        posture: MacroPosture,
        *,
        offset: int = 0,
    ) -> int:
        """Apply the current posture to a category's normal priority."""

        base = {
            "supply": self.supply_priority,
            "worker": self.worker_priority,
            "expansion": self.expansion_priority,
            "gas": self.gas_priority,
            "army": self.army_priority,
            "production": self.production_priority,
            "addon": self.addon_priority,
            "upgrade": self.upgrade_priority,
        }[category]
        adjustment = {
            MacroPosture.DEFENSE: {
                "supply": 4,
                "worker": -31,
                "expansion": -38,
                "gas": -11,
                "army": 25,
                "production": 16,
                "addon": 10,
                "upgrade": -18,
            },
            MacroPosture.BALANCED: {},
            MacroPosture.GREED: {
                "worker": 19,
                "expansion": 27,
                "gas": 9,
                "army": -20,
                "production": -5,
                "addon": -7,
                "upgrade": 2,
            },
            MacroPosture.RECOVERY: {
                "worker": 27,
                "expansion": -18,
                "gas": 4,
                "army": -17,
                "production": 22,
                "addon": 13,
                "upgrade": -23,
            },
        }[posture].get(category, 0)
        return min(100, max(0, base + adjustment + offset))

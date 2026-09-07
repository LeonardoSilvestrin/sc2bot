from dataclasses import dataclass, field

from bot.behavior.macro.goals import MacroGoalSet, bio_three_one_one
from bot.behavior.posture import MacroPosture
from bot.engine.economy.models import ResourceCost


@dataclass(frozen=True, slots=True)
class MacroPlannerConfig:
    """Costs and thresholds used to turn a strategy into spend proposals."""

    goals: MacroGoalSet = field(default_factory=bio_three_one_one)
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
    require_opening_completed: bool = True

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

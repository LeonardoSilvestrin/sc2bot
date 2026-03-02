from bot.tasks.macro.tasks.opening import MacroOpeningTick
from bot.tasks.macro.tasks.production_tick import MacroProductionTick
from bot.tasks.macro.tasks.scv_housekeeping_task import ScvHousekeeping
from bot.tasks.macro.tasks.spending_tick import MacroSpendingTick
from bot.tasks.macro.tasks.tech_tick import MacroTechTick

__all__ = [
    "MacroOpeningTick",
    "MacroProductionTick",
    "MacroSpendingTick",
    "MacroTechTick",
    "ScvHousekeeping",
]

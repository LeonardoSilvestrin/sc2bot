"""Public contracts shared by the bot's modules."""

from .allocation import UnitRequirement
from .commands import MissionCommands
from .economy import (
    EconomicAction,
    EconomicActionKind,
    EconomicActionSnapshot,
    EconomicActionStatus,
    EconomicFeedback,
    EconomicFeedbackKind,
    EconomicProposal,
    EconomyTickResult,
    ResourceBank,
    ResourceCost,
)
from .logging import BotLogger

__all__ = [
    "BotLogger",
    "EconomicAction",
    "EconomicActionKind",
    "EconomicActionSnapshot",
    "EconomicActionStatus",
    "EconomicFeedback",
    "EconomicFeedbackKind",
    "EconomicProposal",
    "EconomyTickResult",
    "MissionCommands",
    "ResourceBank",
    "ResourceCost",
    "UnitRequirement",
]

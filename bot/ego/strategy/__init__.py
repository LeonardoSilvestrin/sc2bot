"""STRATEGY: how the game stands and what the bot wants now.

Awareness -> GameAssessment (`assessment`) -> StrategicIntent (`strategy`) ->
planners. The contracts live in `model`. See docs/architecture.md.
"""

from .assessment import AssessmentConfig, AssessmentModel
from .model import (
    GameAssessment,
    PostureGate,
    StrategicIntent,
    StrategicPosture,
    ThreatBand,
    threat_band,
)
from .strategy import StrategyConfig, StrategyModel, gate_scores

__all__ = [
    "AssessmentConfig",
    "AssessmentModel",
    "GameAssessment",
    "PostureGate",
    "StrategicIntent",
    "StrategicPosture",
    "StrategyConfig",
    "StrategyModel",
    "ThreatBand",
    "gate_scores",
    "threat_band",
]

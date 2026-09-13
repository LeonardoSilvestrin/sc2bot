"""The strategic layer: which objective should dominate right now.

The scoring/director core is pure and runtime-free: it reads ``StrategyInputs``
and returns a
``StrategySnapshot``. The runtime updates it in shadow mode; gameplay does
not consume its objective yet. See
``docs/strategy.md``.
"""

from bot.domain.posture import MacroPosture

from .awareness_adapter import build_strategy_inputs
from .config import (
    BuildAdvantageWeights,
    PressureWeights,
    RecoverWeights,
    StabilizeWeights,
    StrategyConfig,
    TakeMapControlWeights,
)
from .director import StrategicDirector
from .hysteresis import ObjectiveState, decision_confidence, select_objective
from .model import (
    ObjectiveAssessment,
    ScoreContribution,
    StrategicObjective,
    StrategyInputs,
    StrategySnapshot,
)
from .posture import MacroPostureConfig, MacroPostureDirector, MacroPostureState
from .scoring import (
    assess_objectives,
    score_build_advantage,
    score_pressure,
    score_recover,
    score_stabilize,
    score_take_map_control,
)

__all__ = [
    "BuildAdvantageWeights",
    "MacroPosture",
    "MacroPostureConfig",
    "MacroPostureDirector",
    "MacroPostureState",
    "ObjectiveAssessment",
    "ObjectiveState",
    "PressureWeights",
    "RecoverWeights",
    "ScoreContribution",
    "StabilizeWeights",
    "StrategicDirector",
    "StrategicObjective",
    "StrategyConfig",
    "StrategyInputs",
    "StrategySnapshot",
    "TakeMapControlWeights",
    "assess_objectives",
    "build_strategy_inputs",
    "decision_confidence",
    "score_build_advantage",
    "score_pressure",
    "score_recover",
    "score_stabilize",
    "score_take_map_control",
    "select_objective",
]

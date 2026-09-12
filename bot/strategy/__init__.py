"""The strategic layer: which objective should dominate right now.

Pure and runtime-free: it reads ``StrategyInputs`` and returns a
``StrategySnapshot``. Shadow mode -- nothing consumes it yet. See
``_botdev/architecture/strategy.md``.
"""

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
    "decision_confidence",
    "score_build_advantage",
    "score_pressure",
    "score_recover",
    "score_stabilize",
    "score_take_map_control",
    "select_objective",
]

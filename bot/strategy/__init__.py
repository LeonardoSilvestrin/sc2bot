"""The strategic layer: what matters now, and where control is wanted.

The scoring/director core is pure and runtime-free: it reads ``StrategyInputs``
and returns a ``StrategySnapshot``. ``derive_intent`` spells the objective out
as a ``StrategicIntent``, and ``score_mission`` ranks every behavior's
opportunities under it on one scale. See ``docs/strategy.md``.
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
from .intent import IntentConfig, StrategicActivity, StrategicIntent, derive_intent
from .mission_policy import (
    ControlNeed,
    MissionPolicyConfig,
    MissionRanking,
    MissionSignals,
    score_mission,
    to_priority,
)
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
    "ControlNeed",
    "IntentConfig",
    "MacroPosture",
    "MacroPostureConfig",
    "MacroPostureDirector",
    "MacroPostureState",
    "MissionPolicyConfig",
    "MissionRanking",
    "MissionSignals",
    "ObjectiveAssessment",
    "ObjectiveState",
    "PressureWeights",
    "RecoverWeights",
    "ScoreContribution",
    "StabilizeWeights",
    "StrategicActivity",
    "StrategicDirector",
    "StrategicIntent",
    "StrategicObjective",
    "StrategyConfig",
    "StrategyInputs",
    "StrategySnapshot",
    "TakeMapControlWeights",
    "assess_objectives",
    "build_strategy_inputs",
    "decision_confidence",
    "derive_intent",
    "score_build_advantage",
    "score_pressure",
    "score_recover",
    "score_stabilize",
    "score_mission",
    "score_take_map_control",
    "select_objective",
    "to_priority",
]

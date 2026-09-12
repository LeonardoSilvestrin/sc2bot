from __future__ import annotations

import math

from .config import StrategyConfig
from .hysteresis import ObjectiveState, decision_confidence, select_objective
from .model import StrategyInputs, StrategySnapshot
from .scoring import assess_objectives


class StrategicDirector:
    """Holds the dominant strategic objective across updates.

    Each update scores every objective from ``StrategyInputs``, lets
    hysteresis decide whether the objective in force changes, and returns a
    ``StrategySnapshot``. It knows no runtime, snapshot or behavior, and
    performs no I/O.
    """

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self._config = config or StrategyConfig()
        self._state: ObjectiveState | None = None
        self._snapshot: StrategySnapshot | None = None

    @property
    def config(self) -> StrategyConfig:
        return self._config

    @property
    def snapshot(self) -> StrategySnapshot | None:
        """The latest snapshot; ``None`` before the first update."""

        return self._snapshot

    def update(self, inputs: StrategyInputs, game_time: float) -> StrategySnapshot:
        """Recompute the direction, at most once per ``update_interval_seconds``.

        Between recomputations the previous snapshot is returned unchanged
        and ``inputs`` are ignored. The first update enters
        ``initial_objective`` (only an emergency can leave it at once), so
        the direction is never undefined.
        """

        if not math.isfinite(game_time):
            raise ValueError("game_time must be finite")
        last = self._snapshot
        if last is not None:
            if game_time < last.game_time:
                raise ValueError("game_time must not go backwards")
            if game_time - last.game_time < self._config.update_interval_seconds:
                return last

        assessments = assess_objectives(inputs, self._config)
        state = self._state or ObjectiveState(
            objective=self._config.initial_objective, entered_at=game_time
        )
        state = select_objective(
            state=state,
            assessments=assessments,
            immediate_threat=inputs.immediate_threat,
            now=game_time,
            config=self._config,
        )
        self._state = state
        self._snapshot = StrategySnapshot(
            objective=state.objective,
            confidence=decision_confidence(state.objective, assessments, self._config),
            assessments=assessments,
            previous_objective=state.previous,
            game_time=game_time,
            time_in_objective=game_time - state.entered_at,
            inputs=inputs,
        )
        return self._snapshot

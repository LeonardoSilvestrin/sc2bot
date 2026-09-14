from __future__ import annotations

import numpy as np
import pytest
from sc2.position import Point2

from bot.awareness import AwarenessState, BaseThreat, InfluenceField
from bot.ego.strategy import Objective, StrategyModel

from .fakes import MAIN, MAP, NATURAL, attention

EMPTY_FIELD = InfluenceField((), 4.0, np.zeros(0), np.zeros(0), np.zeros(0))


def awareness(
    danger: float, *, own: float = 0.0, enemy: float = 0.0, bases=(MAIN,)
) -> AwarenessState:
    threats = tuple(
        BaseThreat(
            base_id=base.base_id,
            position=base.position,
            is_main=base.is_main,
            pressure=1.0 if danger > 0.0 and index == 0 else 0.0,
            cover=0.0,
            threat=danger if index == 0 else 0.0,
            air_share=0.0,
            center=Point2((base.position.x + 5.0, base.position.y))
            if danger > 0.0 and index == 0
            else None,
        )
        for index, base in enumerate(bases)
    )
    return AwarenessState(
        time=0.0,
        contacts=(),
        bases=threats,
        own_power=own,
        enemy_power=enemy,
        influence=EMPTY_FIELD,
    )


def decide(model: StrategyModel, time: float, danger: float, **kwargs):
    bases = kwargs.pop("bases", (MAIN,))
    return model.decide(attention(time=time, bases=bases), awareness(danger, bases=bases, **kwargs))


def test_no_threat_builds_an_advantage_holding_the_main_ramp() -> None:
    state = decide(StrategyModel(), 0.0, 0.0)

    assert state.objective is Objective.BUILD_ADVANTAGE
    assert state.reason == "no_immediate_threat"
    assert state.previous is None
    assert state.rally == MAP.main_ramp


def test_an_emergency_stabilizes_at_once_and_rallies_at_the_threatened_base() -> None:
    model = StrategyModel()
    decide(model, 0.0, 0.0)

    state = decide(model, 1.0, 0.7)

    assert state.objective is Objective.STABILIZE
    assert state.reason == "emergency_threat"
    assert state.previous is Objective.BUILD_ADVANTAGE
    assert state.rally == MAIN.position


def test_a_moderate_threat_waits_for_the_minimum_dwell() -> None:
    model = StrategyModel()
    decide(model, 0.0, 0.0)

    assert decide(model, 4.0, 0.58).objective is Objective.BUILD_ADVANTAGE
    switched = decide(model, 8.0, 0.58)
    assert switched.objective is Objective.STABILIZE
    assert switched.reason == "base_under_threat"
    assert switched.since == 8.0


def test_a_challenger_inside_the_margin_never_switches() -> None:
    model = StrategyModel()
    decide(model, 0.0, 0.0)

    assert decide(model, 30.0, 0.54).objective is Objective.BUILD_ADVANTAGE


def test_the_threat_clearing_returns_to_build_advantage_after_the_dwell() -> None:
    model = StrategyModel()
    decide(model, 0.0, 0.9)

    assert decide(model, 5.0, 0.0).objective is Objective.STABILIZE
    back = decide(model, 8.0, 0.0)
    assert back.objective is Objective.BUILD_ADVANTAGE
    assert back.previous is Objective.STABILIZE


def test_a_first_tie_is_conservative() -> None:
    assert decide(StrategyModel(), 0.0, 0.5).objective is Objective.STABILIZE


def test_a_forward_base_moves_the_rally_toward_the_enemy() -> None:
    state = decide(StrategyModel(), 0.0, 0.0, bases=(MAIN, NATURAL))

    assert state.rally == NATURAL.position.towards(MAP.enemy_start, 6.0)


@pytest.mark.parametrize("danger", [0.0, 0.3, 1.0])
@pytest.mark.parametrize("own, enemy", [(0.0, 0.0), (10.0, 0.0), (0.0, 10.0), (4.0, 6.0)])
def test_preferences_stay_in_the_unit_interval(danger: float, own: float, enemy: float) -> None:
    state = decide(StrategyModel(), 0.0, danger, own=own, enemy=enemy)

    for value in (state.defense, state.army, state.economy, state.risk):
        assert 0.0 <= value <= 1.0
    assert state.army + state.economy == pytest.approx(1.0)


def test_the_same_awareness_decides_the_same_strategy() -> None:
    sequence = ((0.0, 0.0), (2.0, 0.65), (6.0, 0.2), (15.0, 0.0), (30.0, 0.58))
    first, second = StrategyModel(), StrategyModel()

    for time, danger in sequence:
        assert decide(first, time, danger, own=3.0, enemy=2.0) == decide(
            second, time, danger, own=3.0, enemy=2.0
        )

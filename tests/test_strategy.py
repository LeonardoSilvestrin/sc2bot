from __future__ import annotations

import math

import numpy as np
import pytest
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.awareness import (
    AwarenessConfig,
    AwarenessModel,
    AwarenessState,
    BaseThreat,
    InfluenceField,
)
from bot.ego.planners.map_control import MapControlPlanner
from bot.ego.strategy import EconomyPosture, Objective, StrategyConfig, StrategyModel

from .fakes import MAIN, attention, unit

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
            recent_threat=danger if index == 0 else 0.0,
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


def test_no_threat_builds_an_advantage() -> None:
    state = decide(StrategyModel(), 0.0, 0.0)

    assert state.objective is Objective.BUILD_ADVANTAGE
    assert state.reason == "no_immediate_threat"
    assert state.previous is None


def test_an_emergency_stabilizes_at_once() -> None:
    model = StrategyModel()
    decide(model, 0.0, 0.0)

    state = decide(model, 1.0, 0.7)

    assert state.objective is Objective.STABILIZE
    assert state.reason == "emergency_threat"
    assert state.previous is Objective.BUILD_ADVANTAGE
    assert state.economy_policy.posture is EconomyPosture.SURVIVE


def test_survive_latches_inside_stabilize_and_clears_only_after_leaving() -> None:
    model = StrategyModel()
    first = decide(model, 0.0, 0.58)
    emergency = decide(model, 1.0, 0.7)
    lull = decide(model, 2.0, 0.55)
    back = decide(model, 20.0, 0.0)

    assert first.economy_policy.posture is EconomyPosture.ARMY_FIRST
    assert emergency.economy_policy.posture is EconomyPosture.SURVIVE
    assert lull.objective is Objective.STABILIZE
    assert lull.economy_policy.posture is EconomyPosture.SURVIVE
    assert back.objective is Objective.BUILD_ADVANTAGE
    assert back.economy_policy.posture is EconomyPosture.INVEST


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


@pytest.mark.parametrize("danger", [0.0, 0.3, 1.0])
@pytest.mark.parametrize("own, enemy", [(0.0, 0.0), (10.0, 0.0), (0.0, 10.0), (4.0, 6.0)])
def test_preferences_stay_in_the_unit_interval(danger: float, own: float, enemy: float) -> None:
    state = decide(StrategyModel(), 0.0, danger, own=own, enemy=enemy)

    for value in (state.defense, state.army, state.economy, state.risk):
        assert 0.0 <= value <= 1.0
    assert state.army + state.economy == pytest.approx(1.0)


def test_a_lull_in_an_attack_does_not_send_the_army_away() -> None:
    # Trace 483722e, 1318.7 s: after 44 s of STABILIZE danger fell from 0.63 to
    # 0.33 in one step as attackers died, the rally went ~90 cells to the front,
    # and an emergency brought it back 2.1 s later as 26 more arrived.
    awareness, strategy, map_control = (
        AwarenessModel(),
        StrategyModel(),
        MapControlPlanner(),
    )
    x, y = MAIN.position
    first_wave = tuple(unit(tag, x=x, y=y) for tag in range(1, 5))
    straggler = first_wave[-1:]
    second_wave = straggler + tuple(unit(tag, x=x, y=y) for tag in range(10, 15))
    decided = []
    for step in range(181):
        now = 0.5 * step
        if now <= 44.0:
            enemies, dead = first_wave, ()
        elif now <= 46.0:
            enemies, dead = straggler, (1, 2, 3)
        elif now <= 60.0:
            enemies, dead = second_wave, ()
        else:
            enemies, dead = (), (4, 10, 11, 12, 13, 14)
        frame = attention(time=now, enemy_units=enemies, dead_tags=dead)
        believed = awareness.infer(frame)
        state = strategy.decide(frame, believed)
        decided.append((state, map_control.plan(frame, believed, state).anchor))

    left = [state.time for state, _ in decided if state.objective is Objective.BUILD_ADVANTAGE]
    assert left and left[0] > 60.0
    # Once the attack is over, the army goes back when the remembered threat of
    # the second wave has faded to the switch point, on the first frame after.
    peak = 1.0 - math.exp(-6.0 / AwarenessConfig().full_pressure)
    switch_point = (1.0 - StrategyConfig().switch_margin) / 2.0
    calm_at = 60.0 + AwarenessConfig().threat_memory * math.log(peak / switch_point)
    assert calm_at <= left[0] < calm_at + 0.5
    lull = decided[89][0]
    assert lull.time == 44.5
    assert dict(lull.inputs)["danger_now"] == pytest.approx(1.0 - math.exp(-0.25))
    assert lull.defense == pytest.approx((1.0 - math.exp(-1.0)) * math.exp(-0.5 / 20.0))
    assert all(anchor == MAIN.position for state, anchor in decided if state.time < left[0])


def test_the_fog_is_no_advantage_but_a_fresh_look_at_the_whole_army_is() -> None:
    # Trace 3769f04, 240-560 s: no enemy army in sight, so enemy_power 0,
    # army_share 1.0 and risk 1.0 -- until 45 Marines of it arrived at 575 s.
    x, y = MAIN.position
    own = tuple(unit(tag, x=x, y=y, power=4.7) for tag in range(100, 110))
    config = AwarenessConfig()
    expected = config.army_growth * (500.0 - config.army_onset)
    margin = StrategyConfig().commit_margin

    def inputs(*enemies) -> dict[str, float]:
        frame = attention(time=500.0, own_units=own, enemy_units=enemies)
        return dict(StrategyModel().decide(frame, AwarenessModel().infer(frame)).inputs)

    fog = inputs()
    # 26 Roaches far from our bases: 39 Marines, a little more than expected by now.
    whole = inputs(*(unit(tag, UnitTypeId.ROACH, 50, 50, power=1.5) for tag in range(1, 27)))

    assert fog["enemy_power"] == 0.0
    assert fog["enemy_uncertainty"] == pytest.approx(expected)
    assert fog["planned_enemy_power"] == pytest.approx((1.0 + margin) * expected)
    assert fog["army_share"] == pytest.approx(47.0 / (47.0 + (1.0 + margin) * expected))
    assert 0.0 < fog["army_share"] < 0.5
    assert whole["enemy_uncertainty"] == 0.0
    assert whole["planned_enemy_power"] == pytest.approx(39.0)
    assert whole["army_share"] == pytest.approx(47.0 / 86.0)
    assert whole["army_share"] > 0.5


def test_the_same_awareness_decides_the_same_strategy() -> None:
    sequence = ((0.0, 0.0), (2.0, 0.65), (6.0, 0.2), (15.0, 0.0), (30.0, 0.58))
    first, second = StrategyModel(), StrategyModel()

    for time, danger in sequence:
        assert decide(first, time, danger, own=3.0, enemy=2.0) == decide(
            second, time, danger, own=3.0, enemy=2.0
        )

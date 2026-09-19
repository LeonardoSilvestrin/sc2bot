from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from bot.awareness import (
    AwarenessConfig,
    AwarenessModel,
    AwarenessState,
    BaseThreat,
    InfluenceField,
)
from bot.ego.planners.map_control import MapControlPlanner
from bot.ego.strategy import (
    AssessmentConfig,
    AssessmentModel,
    GameAssessment,
    StrategicPosture,
    StrategyConfig,
    StrategyModel,
    ThreatBand,
    gate_scores,
)

from .fakes import MAIN, NATURAL, attention, unit

EMPTY_FIELD = InfluenceField((), 4.0, np.zeros(0), np.zeros(0), np.zeros(0))
PRIOR = AssessmentConfig().prior_power
DEFEND = StrategicPosture.DEFEND
RECOVER = StrategicPosture.RECOVER
DEVELOP = StrategicPosture.DEVELOP
PRESSURE = StrategicPosture.PRESSURE
COMMIT = StrategicPosture.COMMIT


def awareness(
    danger: float,
    *,
    own: float = 0.0,
    enemy: float = 0.0,
    seen: float = 0.0,
    expected: float = 0.0,
    bases=(MAIN,),
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
        seen_enemy_power=max(seen, enemy),
        expected_enemy_power=expected,
    )


def decide(model: StrategyModel, time: float, danger: float, **kwargs):
    bases = kwargs.pop("bases", (MAIN,))
    supply = kwargs.pop("supply", 20.0)
    frame = replace(attention(time=time, bases=bases), supply_used=supply)
    return model.decide(frame, awareness(danger, bases=bases, **kwargs))


def assessed(**values) -> GameAssessment:
    fields = {
        "time": 0.0,
        "threat_level": 0.0,
        "army_position": 0.0,
        "economy_position": 0.0,
        "enemy_vulnerability": 0.0,
        "power_spike": 0.0,
        "confidence": 1.0,
        "setback": 0.0,
        "upgrade_spike": 0.0,
        "supply_spike": 0.0,
    }
    return GameAssessment(**{**fields, **values})


class Scripted:
    """An assessment model that replays prepared assessments."""

    def __init__(self, *assessments: GameAssessment) -> None:
        self.config = AssessmentConfig()
        self._next = iter(assessments)

    def assess(self, attention, awareness) -> GameAssessment:
        return next(self._next)


def replay(*assessments: GameAssessment):
    model = StrategyModel()
    model.assessment = Scripted(*assessments)
    return [
        model.decide(attention(time=item.time), awareness(item.threat_level))
        for item in assessments
    ]


# The posture: DEFEND is the old STABILIZE, with the same hysteresis.


def test_no_threat_and_no_opportunity_develops() -> None:
    intent = decide(StrategyModel(), 0.0, 0.0)

    assert intent.posture is DEVELOP
    assert intent.reason == "no_opportunity"
    assert intent.previous is None
    assert not intent.emergency


def test_an_emergency_defends_at_once() -> None:
    model = StrategyModel()
    decide(model, 0.0, 0.0)

    intent = decide(model, 1.0, 0.7)

    assert intent.posture is DEFEND
    assert intent.reason == "emergency_threat"
    assert intent.previous is DEVELOP
    assert intent.emergency


def test_the_emergency_latches_inside_defend_and_clears_only_after_leaving() -> None:
    model = StrategyModel()
    first = decide(model, 0.0, 0.58)
    emergency = decide(model, 1.0, 0.7)
    lull = decide(model, 2.0, 0.55)
    back = decide(model, 20.0, 0.0)

    assert (first.posture, first.emergency) == (DEFEND, False)
    assert emergency.emergency
    assert (lull.posture, lull.emergency) == (DEFEND, True)
    assert (back.posture, back.emergency) == (DEVELOP, False)


def test_a_moderate_threat_waits_for_the_minimum_dwell() -> None:
    model = StrategyModel()
    decide(model, 0.0, 0.0)

    assert decide(model, 4.0, 0.58).posture is DEVELOP
    switched = decide(model, 8.0, 0.58)
    assert switched.posture is DEFEND
    assert switched.reason == "home_threatened"
    assert switched.since == 8.0


def test_a_challenger_inside_the_margin_never_switches() -> None:
    model = StrategyModel()
    decide(model, 0.0, 0.0)

    assert decide(model, 30.0, 0.54).posture is DEVELOP


def test_the_threat_clearing_leaves_defend_after_the_dwell() -> None:
    model = StrategyModel()
    decide(model, 0.0, 0.9)

    assert decide(model, 5.0, 0.0).posture is DEFEND
    back = decide(model, 8.0, 0.0)
    assert back.posture is DEVELOP
    assert back.previous is DEFEND
    assert back.reason == "threat_cleared"


def test_a_first_tie_is_conservative() -> None:
    assert decide(StrategyModel(), 0.0, 0.5).posture is DEFEND


@pytest.mark.parametrize("danger", [0.0, 0.3, 1.0])
@pytest.mark.parametrize("own, enemy", [(0.0, 0.0), (10.0, 0.0), (0.0, 10.0), (4.0, 6.0)])
def test_preferences_and_the_assessment_stay_in_range(
    danger: float, own: float, enemy: float
) -> None:
    intent = decide(StrategyModel(), 0.0, danger, own=own, enemy=enemy)
    assessment = intent.assessment

    for value in (intent.defense, intent.army, intent.economy, intent.risk):
        assert 0.0 <= value <= 1.0
    assert intent.army + intent.economy == pytest.approx(1.0)
    for value in (assessment.army_position, assessment.economy_position):
        assert -1.0 <= value <= 1.0
    for gate in intent.gates:
        assert 0.0 <= gate.score <= 1.0


def test_a_lull_in_an_attack_does_not_send_the_army_away() -> None:
    # Trace 483722e, 1318.7 s: after 44 s of STABILIZE danger fell from 0.63 to
    # 0.33 in one step as attackers died, the rally went ~90 cells to the front,
    # and an emergency brought it back 2.1 s later as 26 more arrived.
    awareness_model, strategy, map_control = (
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
        believed = awareness_model.infer(frame)
        intent = strategy.decide(frame, believed)
        decided.append((intent, map_control.plan(frame, believed, intent).anchor))

    left = [intent.time for intent, _ in decided if intent.posture is not DEFEND]
    assert left and left[0] > 60.0
    # Once the attack is over, the army goes back when the remembered threat of
    # the second wave has faded to the switch point, on the first frame after.
    peak = 1.0 - math.exp(-6.0 / AwarenessConfig().full_pressure)
    switch_point = (1.0 - StrategyConfig().switch_margin) / 2.0
    calm_at = 60.0 + AwarenessConfig().threat_memory * math.log(peak / switch_point)
    assert calm_at <= left[0] < calm_at + 0.5
    lull = decided[89][0]
    assert lull.time == 44.5
    assert dict(lull.assessment.inputs)["danger_now"] == pytest.approx(1.0 - math.exp(-0.25))
    assert lull.defense == pytest.approx((1.0 - math.exp(-1.0)) * math.exp(-0.5 / 20.0))
    assert all(anchor == MAIN.position for intent, anchor in decided if intent.time < left[0])


def test_the_same_awareness_decides_the_same_intent() -> None:
    sequence = ((0.0, 0.0), (2.0, 0.65), (6.0, 0.2), (15.0, 0.0), (30.0, 0.58))
    first, second = StrategyModel(), StrategyModel()

    for time, danger in sequence:
        assert decide(first, time, danger, own=3.0, enemy=2.0) == decide(
            second, time, danger, own=3.0, enemy=2.0
        )


# The assessment.


def test_the_fog_is_no_advantage_but_a_fresh_look_at_the_whole_army_is() -> None:
    # Trace 3769f04, 240-560 s: no enemy army in sight, so enemy_power 0,
    # army_share 1.0 and risk 1.0 -- until 45 Marines of it arrived at 575 s.
    x, y = MAIN.position
    own = tuple(unit(tag, x=x, y=y, power=4.7) for tag in range(100, 110))
    config = AwarenessConfig()
    expected = config.army_growth * (500.0 - config.army_onset)
    margin = AssessmentConfig().commit_margin

    def intent(*enemies):
        frame = attention(time=500.0, own_units=own, enemy_units=enemies)
        return StrategyModel().decide(frame, AwarenessModel().infer(frame))

    fog = intent()
    # 26 Roaches far from our bases: 39 Marines, a little more than expected by now.
    whole = intent(*(unit(tag, UnitTypeId.ROACH, 50, 50, power=1.5) for tag in range(1, 27)))
    fog_inputs = dict(fog.assessment.inputs)
    whole_inputs = dict(whole.assessment.inputs)

    assert fog_inputs["enemy_power"] == 0.0
    assert fog_inputs["enemy_uncertainty"] == pytest.approx(expected)
    assert fog_inputs["planned_enemy_power"] == pytest.approx((1.0 + margin) * expected)
    planned = (1.0 + margin) * expected
    assert fog.army_share == pytest.approx((47.0 + PRIOR / 2) / (47.0 + planned + PRIOR))
    assert 0.0 < fog.army_share < 0.5
    # Nothing backs the estimate but the prior.
    assert fog.assessment.confidence == 0.0
    assert whole_inputs["enemy_uncertainty"] == 0.0
    assert whole_inputs["planned_enemy_power"] == pytest.approx(39.0)
    assert whole.army_share == pytest.approx((47.0 + PRIOR / 2) / (47.0 + 39.0 + PRIOR))
    assert whole.army_share > 0.5
    assert whole.assessment.confidence == pytest.approx(1.0)


def test_a_skirmish_between_a_few_units_is_no_verdict() -> None:
    few = decide(StrategyModel(), 0.0, 0.0, own=4.0).assessment
    many = decide(StrategyModel(), 0.0, 0.0, own=80.0, enemy=20.0).assessment

    assert few.army_position == pytest.approx(4.0 / (4.0 + PRIOR))
    assert many.army_position == pytest.approx(60.0 / (100.0 + PRIOR))
    assert few.army_position < many.army_position


def test_confidence_is_the_share_of_the_estimate_backed_by_sightings() -> None:
    assert decide(StrategyModel(), 0.0, 0.0, expected=40.0).assessment.confidence == 0.0
    half = decide(StrategyModel(), 0.0, 0.0, seen=20.0, expected=40.0).assessment
    assert half.confidence == pytest.approx(0.5)
    assert decide(StrategyModel(), 0.0, 0.0, seen=50.0, expected=40.0).assessment.confidence == 1.0
    assert decide(StrategyModel(), 0.0, 0.0).assessment.confidence == 1.0


def lines(*, own_alive, enemy_alive, dead=(), time):
    """Our Marines at our main (power 2) and Zerglings far away (power 1)."""

    return attention(
        time=time,
        own_units=tuple(unit(tag, x=20, y=20, power=2.0) for tag in own_alive),
        enemy_units=tuple(
            unit(tag, UnitTypeId.ZERGLING, 50, 50, power=1.0, attack_air=False)
            for tag in enemy_alive
        ),
        dead_tags=dead,
    )


def test_deaths_become_setback_and_enemy_vulnerability_and_fade() -> None:
    awareness_model, model = AwarenessModel(), AssessmentModel()

    def assess(frame) -> GameAssessment:
        return model.assess(frame, awareness_model.infer(frame))

    assess(lines(own_alive=range(1, 11), enemy_alive=range(101, 111), time=10.0))
    after = assess(
        lines(
            own_alive=range(1, 6),
            enemy_alive=range(101, 103),
            dead=(*range(6, 11), *range(103, 111)),
            time=11.0,
        )
    )
    later = assess(lines(own_alive=range(1, 6), enemy_alive=range(101, 103), time=41.0))
    now, then = dict(after.inputs), dict(later.inputs)

    assert (now["own_lost"], now["enemy_lost"]) == (10.0, 8.0)
    # Half our army died, trading evenly or worse: counted in full.
    assert after.setback == pytest.approx(10.0 / (10.0 + 10.0))
    assert after.enemy_vulnerability == pytest.approx(8.0 / (8.0 + now["estimated_enemy_power"]))
    fade = math.exp(-30.0 / AssessmentConfig().loss_memory)
    assert then["own_lost"] == pytest.approx(10.0 * fade)
    assert then["enemy_lost"] == pytest.approx(8.0 * fade)
    assert later.setback < after.setback


def test_a_setback_counts_less_the_better_it_traded() -> None:
    def setback(enemy_dead: int) -> float:
        awareness_model, model = AwarenessModel(), AssessmentModel()
        enemies = range(101, 121)
        before = lines(own_alive=range(1, 11), enemy_alive=enemies, time=10.0)
        model.assess(before, awareness_model.infer(before))
        dead = (1, 2, *range(101, 101 + enemy_dead))
        after = lines(
            own_alive=range(3, 11), enemy_alive=range(101 + enemy_dead, 121), dead=dead, time=11.0
        )
        return model.assess(after, awareness_model.infer(after)).setback

    # Two Marines (4 of power) of ten lost: a fifth of the army.
    assert setback(4) == pytest.approx(4.0 / 20.0)
    # The same losses while killing three times as much count half.
    assert setback(12) == pytest.approx(4.0 / 20.0 * 2.0 * 4.0 / 16.0)


def test_a_fresh_upgrade_spikes_and_fades() -> None:
    model = AssessmentModel()
    empty = awareness(0.0)
    window = AssessmentConfig().upgrade_window

    def spike(time: float, *upgrades: UpgradeId) -> float:
        frame = replace(attention(time=time), upgrades=frozenset(upgrades))
        return model.assess(frame, empty).upgrade_spike

    assert spike(100.0) == 0.0
    assert spike(100.5, UpgradeId.STIMPACK) == pytest.approx(1.0 - math.exp(-1.0))
    assert spike(100.5 + window, UpgradeId.STIMPACK) == pytest.approx(
        1.0 - math.exp(-math.exp(-1.0))
    )
    # Upgrades done before the first frame never spike.
    first = replace(attention(time=300.0), upgrades=frozenset({UpgradeId.STIMPACK}))
    assert AssessmentModel().assess(first, empty).upgrade_spike == 0.0


@pytest.mark.parametrize("supply, spike", [(150.0, 0.0), (170.0, 0.0), (180.0, 0.5), (195.0, 1.0)])
def test_supply_near_the_cap_is_a_power_spike(supply: float, spike: float) -> None:
    assessment = decide(StrategyModel(), 0.0, 0.0, supply=supply).assessment

    assert assessment.supply_spike == pytest.approx(spike)
    assert assessment.power_spike == pytest.approx(spike)


def test_the_economy_compares_our_bases_with_the_enemy_bases_believed() -> None:
    hatcheries = tuple(
        unit(900 + index, UnitTypeId.HATCHERY, 50 - 5 * index, 50, power=0.0, structure=True)
        for index in range(3)
    )

    def economy(*structures) -> GameAssessment:
        frame = attention(time=300.0, bases=(MAIN, NATURAL), enemy_structures=structures)
        return AssessmentModel().assess(frame, AwarenessModel().infer(frame))

    # Unscouted: the prior -- here capped at half of the map's three expansions.
    fog = economy()
    assert dict(fog.inputs)["expected_enemy_bases"] == pytest.approx(1.5)
    assert fog.economy_position == pytest.approx((2.0 - 1.5) / 3.5)
    scouted = economy(*hatcheries)
    assert dict(scouted.inputs)["known_enemy_bases"] == 3.0
    assert scouted.economy_position == pytest.approx((2.0 - 3.0) / 5.0)


# The questions behind the posture.


def test_pressure_needs_safety_and_strength_or_a_spike_that_is_not_far_behind() -> None:
    assert gate_scores(assessed(army_position=0.4))[PRESSURE] == pytest.approx(0.7)
    assert gate_scores(assessed(army_position=0.4, threat_level=0.5))[PRESSURE] == pytest.approx(
        0.35
    )
    # A spike counts in full from an even army ...
    assert gate_scores(assessed(power_spike=0.9))[PRESSURE] == pytest.approx(0.9)
    # ... and fades as the army falls behind.
    behind = gate_scores(assessed(army_position=-0.5, power_spike=1.0))[PRESSURE]
    assert behind == pytest.approx(0.5)


def test_commit_needs_both_a_clear_advantage_and_a_vulnerable_enemy() -> None:
    both = gate_scores(assessed(army_position=0.6, enemy_vulnerability=0.6))[COMMIT]
    assert both == pytest.approx(0.6)
    assert gate_scores(assessed(army_position=0.9))[COMMIT] == 0.0
    assert gate_scores(assessed(army_position=-0.2, enemy_vulnerability=0.9))[COMMIT] == 0.0


def test_recover_reads_losses_and_a_deficit_as_far_as_sightings_back_it() -> None:
    assert gate_scores(assessed(setback=0.6))[RECOVER] == pytest.approx(0.6)
    seen = gate_scores(assessed(army_position=-0.6, confidence=1.0))[RECOVER]
    guessed = gate_scores(assessed(army_position=-0.6, confidence=0.2))[RECOVER]
    assert seen == pytest.approx(0.6)
    assert guessed == pytest.approx(0.12)


def test_a_clear_advantage_pressures_and_a_won_fight_commits() -> None:
    awareness_model, model = AwarenessModel(), StrategyModel()

    def step(frame):
        return model.decide(frame, awareness_model.infer(frame))

    army = tuple(unit(tag, x=20, y=20) for tag in range(1, 81))
    lings = tuple(
        unit(tag, UnitTypeId.ZERGLING, 50, 50, power=0.9, attack_air=False)
        for tag in range(101, 121)
    )
    step(attention(time=0.0))
    pressure = step(attention(time=200.0, own_units=army, enemy_units=lings))
    commit = step(
        attention(time=201.0, own_units=army, enemy_units=lings[16:], dead_tags=range(101, 117))
    )

    assert (pressure.posture, pressure.reason) == (PRESSURE, "army_advantage")
    assert (commit.posture, commit.previous, commit.reason) == (
        COMMIT,
        PRESSURE,
        "decisive_advantage",
    )
    assert commit.assessment.enemy_vulnerability > 0.5
    assert commit.summary().startswith("PRESSURE -> COMMIT (decisive_advantage): threat=CLEAR")


def test_losing_the_army_recovers_until_the_losses_fade() -> None:
    awareness_model, model = AwarenessModel(), StrategyModel()

    def step(frame):
        return model.decide(frame, awareness_model.infer(frame))

    lings = range(101, 131)
    step(attention(time=0.0))
    step(lines(own_alive=range(1, 16), enemy_alive=lings, time=300.0))
    setback = step(
        lines(
            own_alive=range(1, 6),
            enemy_alive=range(104, 131),
            dead=(*range(6, 16), 101, 102, 103),
            time=301.0,
        )
    )
    after = [
        step(lines(own_alive=range(1, 6), enemy_alive=range(104, 131), time=301.0 + second))
        for second in range(1, 120)
    ]

    assert (setback.posture, setback.reason) == (RECOVER, "army_setback")
    postures = [intent.posture for intent in after]
    back = postures.index(DEVELOP)
    assert set(postures[:back]) == {RECOVER}
    assert set(postures[back:]) == {DEVELOP}
    assert (after[back].reason, after[back].previous) == ("recovered", RECOVER)
    # Held at least the stance dwell.
    assert after[back].time - setback.time >= StrategyConfig().stance_dwell


def test_a_pressure_window_does_not_flap_on_small_variations() -> None:
    shares = [0.0, 0.2, 0.08, 0.16, 0.06, -0.05, 0.14, -0.12, 0.2]
    intents = replay(
        assessed(time=0.0),
        *(
            assessed(time=20.0 + second, army_position=position)
            for second, position in enumerate(shares)
        ),
        assessed(time=40.0, army_position=-0.12),
    )
    postures = [intent.posture for intent in intents]

    # Opens once the share reaches 0.55 (position 0.1) ...
    assert postures[:3] == [DEVELOP, DEVELOP, PRESSURE]
    # ... and holds through the band: a share above 0.45 never closes it, and
    # one below closes it only after the stance dwell.
    assert set(postures[3:-1]) == {PRESSURE}
    assert (postures[-1], intents[-1].reason) == (DEVELOP, "window_closed")


def test_defend_outranks_every_other_question() -> None:
    intents = replay(
        assessed(time=0.0),
        assessed(time=16.0, army_position=0.8, enemy_vulnerability=0.9, threat_level=0.2),
        assessed(time=20.0, army_position=0.8, enemy_vulnerability=0.9, threat_level=0.7),
    )

    assert [intent.posture for intent in intents] == [DEVELOP, COMMIT, DEFEND]
    defend = intents[-1]
    assert defend.assessment.threat is ThreatBand.HIGH
    assert defend.summary() == (
        "COMMIT -> DEFEND (home_threatened): threat=HIGH threat_level=0.70 "
        "army_position=+0.80 enemy_vulnerability=0.90"
    )


def test_after_a_defense_the_window_reopens_on_its_own_evidence() -> None:
    # The pressure gate reads the threat too: it closed while home was
    # threatened, so leaving DEFEND does not surface a stale window.
    intents = replay(
        assessed(time=0.0),
        assessed(time=16.0, army_position=0.4),
        assessed(time=17.0, army_position=0.4, threat_level=0.8),
        assessed(time=30.0, army_position=0.4, threat_level=0.3),
        assessed(time=31.0, army_position=0.4, threat_level=0.1),
    )

    assert [intent.posture for intent in intents] == [
        DEVELOP,
        PRESSURE,
        DEFEND,
        DEVELOP,
        PRESSURE,
    ]
    assert [intent.reason for intent in intents[2:]] == [
        "home_threatened",
        "threat_cleared",
        "army_advantage",
    ]

from __future__ import annotations

import pytest

from bot.awareness import EnemyArmyConfig, EnemyArmyFilter

# A ladder map: fourteen expansions, so the base prior reaches seven.
SITES = 14


def run(observer: EnemyArmyFilter, until: float, start: float = 0.0, step: float = 1.0, **seen):
    """Steps the observer once per `step` seconds over [start, until]."""

    belief = None
    time = start
    while time <= until + 1e-9:
        belief = observer.update(now=time, base_sites=SITES, **{"seen": 0.0, **seen})
        time += step
    return belief


def test_never_seen_the_army_grows_with_the_economy_and_the_doubt_with_it() -> None:
    observer = EnemyArmyFilter()
    early = run(observer, 300.0)
    late = run(observer, 600.0, start=301.0)

    assert 0.0 < early.power < late.power
    assert 0.0 < early.sigma < late.sigma
    # bench/t0 replays: 4-16 Marines of army paid for by 300 s, 54-109 by 600 s.
    assert 5.0 < early.power < 20.0
    assert 50.0 < late.power < 110.0
    assert late.correction == "none"
    assert late.workers == pytest.approx(min(80.0, 12.0 + 0.1 * 600.0), abs=0.2)


def test_the_army_never_outgrows_the_supply_its_workers_leave() -> None:
    belief = run(EnemyArmyFilter(), 1500.0)
    config = EnemyArmyConfig()

    assert belief.workers == config.max_workers
    assert belief.cap == pytest.approx(config.power_per_supply * (200.0 - 80.0))
    assert belief.power == pytest.approx(belief.cap)
    assert belief.production == 0.0
    # Held at the cap, the doubt is the cap's own.
    assert belief.sigma <= config.cap_sigma + 1e-6


def test_the_army_seen_to_die_leaves_the_estimate_at_once_and_costs_no_certainty() -> None:
    observer = EnemyArmyFilter()
    before = run(observer, 600.0)
    after = observer.update(now=601.0, seen=0.0, army_lost=30.0, base_sites=SITES)

    assert after.lost == 30.0
    assert after.power == pytest.approx(before.power + before.production - 30.0, abs=0.05)
    assert after.sigma >= before.sigma


def test_a_sighting_above_the_prediction_is_believed_and_a_richer_enemy_learned() -> None:
    observer = EnemyArmyFilter()
    predicted = run(observer, 400.0)
    seen = predicted.power + 40.0
    corrected = observer.update(now=401.0, seen=seen, base_sites=SITES)

    assert corrected.correction == "lower_bound"
    assert corrected.power >= seen
    assert corrected.sigma < predicted.sigma
    # More than its economy explained: it produces more than the prior believed.
    assert corrected.growth > EnemyArmyConfig().growth
    assert corrected.production > predicted.production


def test_looking_at_their_bases_and_finding_little_lowers_the_estimate() -> None:
    observer = EnemyArmyFilter()
    predicted = run(observer, 600.0)
    looked = run(observer, 630.0, start=601.0, seen=5.0, coverage=1.0)

    assert looked.correction == "coverage"
    assert 5.0 <= looked.power < 0.5 * predicted.power
    assert looked.sigma < predicted.sigma
    # Less than its economy explained: it is believed to produce less.
    assert looked.growth < EnemyArmyConfig().growth


def test_a_half_look_tells_less_than_a_whole_one() -> None:
    half, whole = EnemyArmyFilter(), EnemyArmyFilter()
    run(half, 600.0)
    run(whole, 600.0)
    half_look = run(half, 610.0, start=601.0, seen=5.0, coverage=0.5)
    whole_look = run(whole, 610.0, start=601.0, seen=5.0, coverage=1.0)

    assert whole_look.power < half_look.power


def test_bases_are_the_prior_or_what_is_known_less_what_was_seen_to_die() -> None:
    observer = EnemyArmyFilter()
    prior = run(observer, 900.0)
    razed = observer.update(now=901.0, seen=0.0, townhalls_lost=3, base_sites=SITES)
    known = observer.update(now=902.0, seen=0.0, known_bases=5, base_sites=SITES)

    assert prior.bases == prior.expected_bases == pytest.approx(7.0)
    assert razed.bases == pytest.approx(4.0)
    assert known.bases == 5.0


def test_workers_seen_to_die_cut_the_production_they_paid_for() -> None:
    observer = EnemyArmyFilter()
    before = run(observer, 500.0)
    after = observer.update(now=501.0, seen=0.0, workers_lost=40, base_sites=SITES)

    assert after.workers == pytest.approx(before.workers - 40.0, abs=0.2)
    assert after.production < 0.6 * before.production


def test_the_workers_known_are_the_least_believed() -> None:
    belief = EnemyArmyFilter().update(now=100.0, seen=0.0, known_workers=30, base_sites=SITES)

    assert belief.workers == 30.0


def test_the_share_of_income_spent_on_army_ramps_from_early_to_late() -> None:
    config = EnemyArmyConfig()
    observer = EnemyArmyFilter(config)

    assert observer.share(0.0) == config.early_share
    assert observer.share(config.share_until + 1.0) == config.late_share
    middle = 0.5 * (config.share_from + config.share_until)
    assert observer.share(middle) == pytest.approx(0.5 * (config.early_share + config.late_share))


@pytest.mark.parametrize(
    "change",
    [
        {"growth": 0.0},
        {"growth": 0.05},
        {"early_share": 0.8},
        {"share_until": 100.0},
        {"coverage_sigma": 0.0},
        {"power_drift": -1.0},
    ],
)
def test_an_invalid_observer_is_rejected(change: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        EnemyArmyConfig(**change)

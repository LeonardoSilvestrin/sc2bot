"""ENEMY ARMY: a state observer for the enemy army and the economy that pays for it.

The enemy army is a state the bot never sees whole. Instead of a prior that
grows with game time and that nothing can refute, it is *predicted* from the
economy behind it and *corrected* by what is seen, as a Kalman filter:

    B  = max(known townhalls, min(sites / 2, 1 + t / base_interval) - townhalls seen to die)
    W' = min(room, W + worker_rate * dt) - workers seen to die,   room = min(max_workers, 22 B)
    u  = min(W, 22 B) * f(t)                       workers' worth of income spent on army
    A' = A + dt * g * u - D                        D: enemy army power seen to die
    g' = g                                         power per worker-second, adapted online

`f(t)` is the share of income that goes to army: `early_share` until
`share_from`, rising linearly to `late_share` at `share_until`. The army never
grows past what the supply left by the workers holds:
`cap = power_per_supply * (max_supply - W)`. A prediction held at the cap is a
constraint met, so its doubt is no larger than the cap's own (`cap_sigma`):
nothing plans against more army than the supply can hold.

The filtered state is x = (A, g), with the transition F = [[1, dt u], [0, 1]]
and the measurement H = [1, 0]. Putting the production parameter g in the
state is what makes the observer adaptive: when the enemy shows more army than
was predicted, the innovation raises A *and* g through their covariance, so an
enemy that out-produces the prior -- a cheating AI's income, or a greedy one
that turns it all into army -- is learned, and so is one that produces less.

Two measurements, both of the power seen alive and not seen to die (`seen`),
which is a lower bound of the army, never all of it:

- lower bound: when the prediction falls below `seen`, the update pulls it up
  with `lower_sigma`, and the estimate is never left below `seen`;
- coverage: while a share `c` of the enemy's known bases is in vision, `seen`
  also measures the army from above, with R = coverage_sigma^2 / (c dt): the
  longer and the more of their bases we look at without finding the army, the
  more we believe it is not there.

The army seen to die is a known input, not a measurement: it leaves the
estimate at once and costs no certainty. Of all the changes from the old prior
this is the one that matters most: in the `bench/t0` replays the bot won every
fight that decided a game and went on believing in 78-100 Marines of enemy
army that had stopped existing (docs/architecture.md, "Observador do
exército inimigo").
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Absorbs float noise in the covariance.
_EPSILON = 1e-12

NO_CORRECTION = "none"
LOWER_BOUND = "lower_bound"
COVERAGE = "coverage"


@dataclass(frozen=True, slots=True)
class EnemyArmyConfig:
    # Workers: the start, how fast they are added, how many a base employs and
    # the most anyone builds.
    start_workers: float = 12.0
    worker_rate: float = 0.1
    workers_per_base: float = 22.0
    max_workers: float = 80.0
    # The enemy is believed to take one more base every this many seconds, up
    # to half the map's expansions, unless more are seen.
    base_interval: float = 150.0
    # Share of income spent on army: early, and late, with a linear ramp between.
    early_share: float = 0.15
    late_share: float = 0.65
    share_from: float = 240.0
    share_until: float = 600.0
    # Power, in Marines, one worker's income buys per second at full army
    # share; its prior, the bounds the filter may adapt it to, and how fast it
    # may drift (variance per second).
    growth: float = 0.008
    growth_sigma: float = 0.003
    growth_min: float = 0.002
    growth_max: float = 0.03
    growth_drift: float = 1.5e-8
    # Variance per second of the army itself, beyond what the economy explains.
    power_drift: float = 0.05
    # How sure a sighting above the prediction is, and how much an empty look
    # at the enemy's bases tells, per second of looking.
    lower_sigma: float = 2.0
    coverage_sigma: float = 15.0
    # The army fits in the supply the workers leave.
    power_per_supply: float = 0.9
    max_supply: float = 200.0
    # How uncertain the cap itself is, in Marines: power per supply varies
    # with what the army is made of.
    cap_sigma: float = 15.0

    def __post_init__(self) -> None:
        for name in (
            "workers_per_base",
            "max_workers",
            "base_interval",
            "growth",
            "growth_sigma",
            "growth_max",
            "lower_sigma",
            "coverage_sigma",
            "power_per_supply",
            "max_supply",
            "cap_sigma",
        ):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        for name in ("start_workers", "worker_rate", "growth_drift", "power_drift", "growth_min"):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must not be negative")
        if not 0.0 <= self.early_share <= self.late_share <= 1.0:
            raise ValueError("0 <= early_share <= late_share <= 1 must hold")
        if not 0.0 <= self.share_from < self.share_until:
            raise ValueError("0 <= share_from < share_until must hold")
        if not self.growth_min <= self.growth <= self.growth_max:
            raise ValueError("growth must lie within [growth_min, growth_max]")


@dataclass(frozen=True, slots=True)
class EnemyArmyBelief:
    """The observer's state after this frame."""

    # The enemy army believed, in Marines, and its standard deviation.
    power: float = 0.0
    sigma: float = 0.0
    # Power one worker's income buys per second at full army share, as adapted.
    growth: float = 0.0
    growth_sigma: float = 0.0
    # Army the enemy is believed to add per second now.
    production: float = 0.0
    workers: float = 0.0
    bases: float = 0.0
    known_bases: float = 0.0
    # The base prior, before the townhalls seen to die are taken off.
    expected_bases: float = 0.0
    # Share of the enemy's known bases in vision now.
    coverage: float = 0.0
    # The most army the supply holds.
    cap: float = 0.0
    # Army power seen to die this frame.
    lost: float = 0.0
    # Which measurement corrected the prediction this frame.
    correction: str = NO_CORRECTION


class EnemyArmyFilter:
    def __init__(self, config: EnemyArmyConfig | None = None) -> None:
        self.config = config or EnemyArmyConfig()
        self._then: float | None = None
        self._power = 0.0
        self._growth = self.config.growth
        # The covariance of (A, g).
        self._paa = 0.0
        self._pag = 0.0
        self._pgg = self.config.growth_sigma**2
        self._workers = self.config.start_workers
        self._townhalls_lost = 0

    def share(self, now: float) -> float:
        """f(t): the share of income spent on army."""

        config = self.config
        ramp = (now - config.share_from) / (config.share_until - config.share_from)
        ramp = min(1.0, max(0.0, ramp))
        return config.early_share + ramp * (config.late_share - config.early_share)

    def update(
        self,
        *,
        now: float,
        seen: float,
        army_lost: float = 0.0,
        workers_lost: int = 0,
        townhalls_lost: int = 0,
        known_bases: int = 0,
        known_workers: int = 0,
        coverage: float = 0.0,
        base_sites: int = 0,
    ) -> EnemyArmyBelief:
        """One frame: predict from the economy, then correct by what is seen.

        `seen`: the enemy army power seen alive and not seen to die;
        `army_lost`, `workers_lost`, `townhalls_lost`: what was seen to die
        this frame; `coverage`: the share of the enemy's known bases in vision;
        `base_sites`: the map's expansions."""

        config = self.config
        dt = 0.0 if self._then is None else max(0.0, now - self._then)
        self._then = now

        # The economy: bases, then the workers they employ.
        self._townhalls_lost += townhalls_lost
        expected = min(max(1.0, 0.5 * base_sites), 1.0 + max(0.0, now) / config.base_interval)
        bases = max(float(known_bases), max(0.0, expected - self._townhalls_lost))
        employed = config.workers_per_base * bases
        room = min(config.max_workers, employed)
        workers = self._workers
        if workers < room:
            workers = min(room, workers + config.worker_rate * dt)
        workers = max(float(known_workers), max(0.0, workers - workers_lost))
        self._workers = workers
        cap = config.power_per_supply * max(0.0, config.max_supply - workers)
        producing = 0.0 if self._power >= cap else min(workers, employed) * self.share(now)

        # Predict: x' = F x + (0, 0) - (D, 0), P' = F P F^T + Q.
        lever = dt * producing
        power = self._power + lever * self._growth - army_lost
        growth = self._growth
        paa = self._paa + 2.0 * lever * self._pag + lever * lever * self._pgg
        paa += config.power_drift * dt
        pag = self._pag + lever * self._pgg
        pgg = self._pgg + config.growth_drift * dt
        if power >= cap:
            # The supply holds no more: the doubt is the cap's, not the growth's.
            bound = config.cap_sigma**2
            if paa > bound:
                pag *= math.sqrt(bound / paa)
                paa = bound
        power = min(max(power, 0.0), cap)

        # Correct by what is seen.
        correction = NO_CORRECTION
        if seen > power:
            power, growth, paa, pag, pgg = _measure(
                power, growth, paa, pag, pgg, seen, config.lower_sigma**2
            )
            correction = LOWER_BOUND
        elif coverage > 0.0 and dt > 0.0 and seen < power:
            noise = config.coverage_sigma**2 / (coverage * dt)
            power, growth, paa, pag, pgg = _measure(power, growth, paa, pag, pgg, seen, noise)
            correction = COVERAGE
        # The army is at least what was seen alive, and fits in the supply
        # unless more than that was seen.
        power = min(max(power, seen, 0.0), max(cap, seen))
        growth = min(config.growth_max, max(config.growth_min, growth))

        self._power, self._growth = power, growth
        self._paa, self._pag, self._pgg = paa, pag, pgg
        return EnemyArmyBelief(
            power=power,
            sigma=math.sqrt(paa),
            growth=growth,
            growth_sigma=math.sqrt(pgg),
            production=0.0 if power >= cap else growth * producing,
            workers=workers,
            bases=bases,
            known_bases=float(known_bases),
            expected_bases=expected,
            coverage=coverage,
            cap=cap,
            lost=army_lost,
            correction=correction,
        )


def _measure(
    power: float,
    growth: float,
    paa: float,
    pag: float,
    pgg: float,
    measured: float,
    noise: float,
) -> tuple[float, float, float, float, float]:
    """The Kalman update with H = [1, 0]."""

    total = paa + noise
    if total <= _EPSILON:
        return power, growth, paa, pag, pgg
    gain_power, gain_growth = paa / total, pag / total
    innovation = measured - power
    return (
        power + gain_power * innovation,
        growth + gain_growth * innovation,
        max(0.0, (1.0 - gain_power) * paa),
        (1.0 - gain_power) * pag,
        max(_EPSILON, pgg - gain_growth * pag),
    )

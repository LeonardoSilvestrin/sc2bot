"""A running estimate of one enemy quantity we only ever partly see.

The enemy's army supply or worker count is never observed whole. Two things
are known: what was seen and not seen dying (``known``, a floor that
survives losing vision), and an assumption for an enemy we know nothing
about -- the ``prior``, about as big as we are. The belief is carried as a
*gap* from that prior, scaled by the prior's size, together with how
informative the reading behind it was:

    enemy ~ max(reading, prior + scale * information * gap)

Because the gap is relative, the belief follows the prior as both armies
grow instead of lagging behind it. ``information`` decays on
``forget_time_constant`` and is only replaced by a reading at least as
informative, so a good scout is remembered for a while and repeated
glimpses of the same corner never add up to having seen everything.
Whatever lies above ``known`` is drawn as a normal cut at zero -- the
maximum-entropy shape for a non-negative quantity of given mean and spread --
placed so that its mean is exactly the believed one: an enemy believed to
have nothing is not quietly assumed to have something, nor one with a wide
doubt assumed to have almost nothing.

Every rate is a time constant, never a per-tick step, so the same game
yields the same belief however often it is stepped.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from statistics import NormalDist

_NORMAL = NormalDist()
# Quantile samples of the unseen remainder used to integrate ``advantage``.
_QUADRATURE_POINTS = 24


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True, slots=True)
class EstimateConfig:
    # Spread of the prior, as a share of its scale: how far an unscouted
    # enemy "our size" can plausibly be from that.
    prior_relative_sd: float = 0.35
    # Spread left when the whole enemy is in view: counts are exact, but
    # supply is only a stand-in for what an army is worth.
    evidence_relative_sd: float = 0.15
    # Our own number is not exact fighting value either.
    own_relative_sd: float = 0.15
    # Absolute doubt in any comparison, about two units' worth: one Reaper
    # against one Marine says nothing about who is ahead.
    noise_floor: float = 4.0
    # The prior's doubt stops shrinking below this size.
    scale_floor: float = 8.0
    # How fast the belief takes on a better reading, and forgets one.
    observe_time_constant: float = 5.0
    forget_time_constant: float = 90.0
    # A sighting this old counts about a third as current information.
    evidence_time_constant: float = 20.0
    # A unit nobody saw die still fades from ``known`` on this scale.
    attrition_time_constant: float = 300.0
    # Scouting never shows everything at once.
    max_information: float = 0.85

    def __post_init__(self) -> None:
        for name in (
            "prior_relative_sd",
            "evidence_relative_sd",
            "own_relative_sd",
            "noise_floor",
            "scale_floor",
            "observe_time_constant",
            "forget_time_constant",
            "evidence_time_constant",
            "attrition_time_constant",
            "max_information",
        ):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if self.observe_time_constant > self.forget_time_constant:
            raise ValueError(
                "observe_time_constant must not exceed forget_time_constant"
            )
        if self.max_information > 1.0:
            raise ValueError("max_information must not exceed 1")


@dataclass(frozen=True, slots=True)
class QuantityEstimate:
    """One enemy quantity: ``known`` plus an unseen remainder.

    ``unseen`` and ``spread`` are the remainder's mean and standard
    deviation. ``gap`` and ``information`` are what the next update builds on.
    """

    known: float
    unseen: float
    spread: float
    gap: float
    information: float
    updated_at: float

    @property
    def mean(self) -> float:
        return self.known + self.unseen


@dataclass(frozen=True, slots=True)
class RosterEvidence:
    # Everything seen and not seen dying, each fading by attrition.
    known: float
    # Share of ``known`` that is current, 0..1; 0 when nothing is known:
    # not having seen anything is not information about how much there is.
    freshness: float


def roster_evidence(
    amounts: Iterable[tuple[float, float]], *, now: float, config: EstimateConfig
) -> RosterEvidence:
    """Sum ``(amount, last_seen_at)`` pairs into a floor and its freshness."""

    known = 0.0
    current = 0.0
    for amount, last_seen_at in amounts:
        age = max(0.0, now - last_seen_at)
        remembered = amount * math.exp(-age / config.attrition_time_constant)
        known += remembered
        current += remembered * math.exp(-age / config.evidence_time_constant)
    return RosterEvidence(
        known=known, freshness=current / known if known > 0.0 else 0.0
    )


def advance_estimate(
    previous: QuantityEstimate | None,
    *,
    now: float,
    known: float,
    reading: float,
    prior: float,
    information: float,
    config: EstimateConfig,
    prior_scale: float | None = None,
) -> QuantityEstimate:
    """Fold this update's evidence into the belief.

    ``reading`` is the best direct estimate of the whole (at least
    ``known``; e.g. workers projected from confirmed bases). ``information``
    (0..1) is how much of the enemy it could have covered. A reading less
    informative than what is still remembered leaves the gap alone; it can
    only raise the belief through ``reading`` itself.

    ``prior_scale`` is what the prior's doubt is proportional to, when that
    is not the prior itself: an enemy army assumed from our total supply is
    uncertain by a share of that total, not of the army.
    """

    known = max(0.0, known)
    reading = max(reading, known)
    prior = max(0.0, prior)
    scale = max(prior if prior_scale is None else prior_scale, config.scale_floor)
    quality = min(clamp01(information), config.max_information)
    observed_gap = (reading - prior) / scale
    if previous is None:
        held, gap = quality, observed_gap
    else:
        elapsed = max(0.0, now - previous.updated_at)
        held = previous.information * math.exp(
            -elapsed / config.forget_time_constant
        )
        gap = previous.gap
        if quality >= held:
            follow = 1.0 - math.exp(-elapsed / config.observe_time_constant)
            held += (quality - held) * follow
            gap += (observed_gap - gap) * follow

    mean = max(reading, prior + scale * held * gap)
    reading_spread = config.evidence_relative_sd * max(reading, config.scale_floor)
    spread = (1.0 - held) * config.prior_relative_sd * scale + held * reading_spread
    return QuantityEstimate(
        known=known,
        unseen=mean - known,
        spread=spread,
        gap=gap,
        information=held,
        updated_at=now,
    )


def advantage(own: float, estimate: QuantityEstimate, config: EstimateConfig) -> float:
    """Probability that ``own`` exceeds the enemy quantity, 0..1.

    Integrated over quantiles of the unseen remainder, so the floor is
    honoured: having seen more than we have proves we are not ahead, however
    little else is known. What is known on either side is only a count, not
    fighting value, so both carry a spread of their own.
    """

    own_spread = math.hypot(
        config.own_relative_sd * own,
        config.evidence_relative_sd * estimate.known,
        config.noise_floor,
    )
    margin = own - estimate.known
    samples = _unseen_quantiles(estimate.unseen, estimate.spread)
    return sum(
        _NORMAL.cdf((margin - unseen) / own_spread) for unseen in samples
    ) / len(samples)


# How far below zero the cut normal's location may sit, in spreads. Past it
# the shape stops changing and samples are rescaled to the mean instead.
_LOWEST_LOCATION = -6.0


def _cut_normal_mean(location: float, spread: float) -> float:
    ratio = location / spread
    return location + spread * _NORMAL.pdf(ratio) / _NORMAL.cdf(ratio)


def _unseen_quantiles(mean: float, spread: float) -> tuple[float, ...]:
    """Quantile midpoints of Normal(location, spread) cut at zero, with the
    location chosen so the cut distribution's mean is ``mean``."""

    if mean <= 1e-9:
        return (0.0,)
    if spread <= 1e-9:
        return (mean,)
    low = _LOWEST_LOCATION * spread
    rescale = 1.0
    lowest_mean = _cut_normal_mean(low, spread)
    if mean <= lowest_mean:
        location, rescale = low, mean / lowest_mean
    else:
        high = mean
        for _ in range(48):
            middle = 0.5 * (low + high)
            if _cut_normal_mean(middle, spread) < mean:
                low = middle
            else:
                high = middle
        location = 0.5 * (low + high)
    above_zero = _NORMAL.cdf(location / spread)
    return tuple(
        rescale
        * max(
            0.0,
            location
            + spread
            * _NORMAL.inv_cdf(
                1.0 - above_zero * (1.0 - (index + 0.5) / _QUADRATURE_POINTS)
            ),
        )
        for index in range(_QUADRATURE_POINTS)
    )


def confidence(estimate: QuantityEstimate, config: EstimateConfig) -> float:
    """How informed the belief still is, 0..1."""

    return clamp01(estimate.information / config.max_information)

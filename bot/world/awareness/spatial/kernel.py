"""The math every spatial reading in Awareness shares.

``K(d, sigma) = exp(-0.5 * d**2 / sigma**2)`` spreads one source smoothly over
the map, and ``S(x) = 1 - exp(-x)`` saturates what several sources add up to,
so a field built from them stays continuous and within [0, 1). The spatial
field and the territory reading are both built from these, so a force means
the same thing to each of them.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import NamedTuple, Protocol

from sc2.position import Point2

# A force only speaks for a point's confidence where it reaches the point with
# at least this much of its weight.
_CONFIDENCE_LOCALITY = 0.01
# Keeps a zero-strength force from vanishing out of the confidence weighting.
_MIN_CONFIDENCE_STRENGTH = 0.01


class ForcePresence(Protocol):
    """What spreading a force's influence needs to know about it."""

    @property
    def center(self) -> Point2: ...

    @property
    def radius(self) -> float: ...

    @property
    def position_uncertainty(self) -> float: ...

    @property
    def combat_strength(self) -> float: ...

    @property
    def anti_ground_strength(self) -> float: ...

    @property
    def confidence(self) -> float: ...


class ForceInfluence(NamedTuple):
    """What believed forces add up to at one point, before saturation."""

    # Each force's strength, scaled by its confidence and by how far it reaches.
    raw: float
    # Locality- and strength-weighted confidence of the forces that reach the
    # point; 0.0 where none does. No evidence is unknown, not known-empty.
    confidence: float
    # ``raw`` as if every force were seen this instant: how much the forces
    # would weigh here, however much they are still believed.
    evidence: float


def saturate(value: float) -> float:
    return 1.0 - math.exp(-max(0.0, value))


def kernel_squared(squared_distance: float, sigma: float) -> float:
    return math.exp(-0.5 * squared_distance / (sigma * sigma))


def distance_squared(first: Point2, second: Point2) -> float:
    dx = float(first.x - second.x)
    dy = float(first.y - second.y)
    return dx * dx + dy * dy


def force_influence(
    point: Point2,
    forces: Iterable[ForcePresence],
    *,
    sigma: float,
    full_strength: float,
    ground_only: bool = False,
) -> ForceInfluence:
    """Unsaturated influence of believed forces at ``point``.

    Each force spreads over ``sigma`` plus its own radius and how far it may
    have moved since it was seen, and weighs ``strength * confidence /
    full_strength``: a stale force reaches wider but weaker, and fades out as
    its confidence does. ``ground_only`` counts only the strength that can
    fight ground units.
    """

    raw = evidence = confidence_weight = weighted_confidence = 0.0
    for force in forces:
        strength = force.anti_ground_strength if ground_only else force.combat_strength
        spread = sigma + force.radius + force.position_uncertainty
        locality = kernel_squared(distance_squared(point, force.center), spread)
        raw += strength * force.confidence * locality / full_strength
        evidence += strength * locality / full_strength
        if locality > _CONFIDENCE_LOCALITY:
            weight = locality * max(strength, _MIN_CONFIDENCE_STRENGTH)
            confidence_weight += weight
            weighted_confidence += weight * force.confidence
    confidence = (
        weighted_confidence / confidence_weight if confidence_weight > 0.0 else 0.0
    )
    return ForceInfluence(raw=raw, confidence=confidence, evidence=evidence)


def same_version(current: tuple, cached: tuple | None) -> bool:
    """Identity is the O(1) version token; equality only runs when it fails."""

    return current is cached or (cached is not None and current == cached)


def cadence_due(now: float, last: float | None, interval: float) -> bool:
    """A cadenced reading is due when never computed, when the clock went
    back, or once ``interval`` has passed since it was."""

    return last is None or now < last or now - last >= interval

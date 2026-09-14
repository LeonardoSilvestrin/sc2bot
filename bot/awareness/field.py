"""The math every spatial reading of Awareness shares.

``K(d, sigma) = exp(-0.5 * d**2 / sigma**2)`` spreads one source smoothly over
the map and ``S(x) = 1 - exp(-x)`` saturates what several sources add up to,
so every reading stays continuous and inside [0, 1). Position uncertainty
widens a source's *possible* threat; it never creates confirmed presence.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sc2.position import Point2

# Presentation only: how the field is summarized in logs and drawings.
PRESENCE_FLOOR = 0.05
CONTROL_BAND = 0.15


@dataclass(frozen=True, slots=True)
class Source:
    x: float
    y: float
    # Already divided by the strength that saturates to 1 - 1/e.
    strength: float
    sigma: float
    # Physical range: no influence at all beyond it.
    reach: float = math.inf


def kernel(squared_distance, sigma):
    return np.exp(-0.5 * squared_distance / (sigma * sigma))


def saturate(value):
    return 1.0 - np.exp(-np.maximum(0.0, value))


def accumulate(xs: np.ndarray, ys: np.ndarray, sources: Sequence[Source]) -> np.ndarray:
    """``sum(strength * K(d, sigma))`` at every point, before saturation."""

    total = np.zeros(xs.shape, dtype=float)
    if not sources:
        return total
    sx = np.array([source.x for source in sources])
    sy = np.array([source.y for source in sources])
    strength = np.array([source.strength for source in sources])
    sigma = np.array([source.sigma for source in sources])
    reach = np.array([source.reach for source in sources])
    squared = (xs[:, None] - sx[None, :]) ** 2 + (ys[:, None] - sy[None, :]) ** 2
    weight = strength[None, :] * kernel(squared, sigma[None, :])
    return np.where(squared <= reach[None, :] ** 2, weight, 0.0).sum(axis=1)


@dataclass(frozen=True, slots=True, eq=False)
class InfluenceField:
    """Readings at every lattice point, aligned with ``positions``."""

    positions: tuple[Point2, ...]
    spacing: float
    # Possible enemy combat presence, widened by position uncertainty.
    threat: np.ndarray
    # Our army and structures.
    support: np.ndarray
    # Credible enemy presence: no uncertainty widening.
    enemy: np.ndarray

    @property
    def control(self) -> np.ndarray:
        return self.support - self.enemy

    def nearest(self, point: Point2) -> int:
        """Index of the sample closest to ``point``; -1 on an empty field."""

        if not self.positions:
            return -1
        xs = np.array([position.x for position in self.positions])
        ys = np.array([position.y for position in self.positions])
        return int(np.argmin((xs - point.x) ** 2 + (ys - point.y) ** 2))

    def summary(self) -> dict[str, float | int]:
        samples = len(self.positions)
        if not samples:
            return {
                "samples": 0,
                "friendly": 0,
                "contested": 0,
                "enemy": 0,
                "threatened": 0,
                "max_threat": 0.0,
            }
        control = self.control
        present = np.maximum(self.support, self.enemy) > PRESENCE_FLOOR
        return {
            "samples": samples,
            "friendly": int(np.sum(present & (control > CONTROL_BAND))),
            "contested": int(np.sum(present & (np.abs(control) <= CONTROL_BAND))),
            "enemy": int(np.sum(present & (control < -CONTROL_BAND))),
            "threatened": int(np.sum(self.threat > PRESENCE_FLOOR)),
            "max_threat": float(self.threat.max()),
        }


def build_field(
    positions: tuple[Point2, ...],
    spacing: float,
    xs: np.ndarray,
    ys: np.ndarray,
    *,
    threat: Sequence[Source],
    support: Sequence[Source],
    enemy: Sequence[Source],
) -> InfluenceField:
    readings = [saturate(accumulate(xs, ys, sources)) for sources in (threat, support, enemy)]
    for reading in readings:
        reading.setflags(write=False)
    return InfluenceField(positions, spacing, *readings)

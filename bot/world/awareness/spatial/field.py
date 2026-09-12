from __future__ import annotations

from dataclasses import dataclass, field

from sc2.position import Point2


@dataclass(frozen=True, slots=True)
class SpatialFieldSample:
    """Independent world properties measured at one pathable map point."""

    position: Point2
    friendly_value: float = 0.0
    enemy_threat: float = 0.0
    choke_value: float = 0.0
    route_value: float = 0.0
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class SpatialField:
    """A coarse continuous-map approximation exposed by Awareness."""

    samples: tuple[SpatialFieldSample, ...] = field(default_factory=tuple)
    updated_at: float = 0.0
    sample_spacing: float = 10.0

    @property
    def candidates(self) -> tuple[SpatialFieldSample, ...]:
        return self.samples

    def at(self, position: Point2) -> SpatialFieldSample | None:
        """Return the nearest sampled reading to an arbitrary map position."""

        return min(
            self.samples,
            key=lambda sample: sample.position.distance_to(position),
            default=None,
        )

    def near(self, position: Point2, radius: float) -> tuple[SpatialFieldSample, ...]:
        if radius < 0.0:
            raise ValueError("radius must not be negative")
        return tuple(
            sorted(
                (
                    sample
                    for sample in self.samples
                    if sample.position.distance_to(position) <= radius
                ),
                key=lambda sample: sample.position.distance_to(position),
            )
        )

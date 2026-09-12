"""What a unit can do, what a job needs, and how well the two match.

Capabilities are operational heuristics on a shared 0..1 scale, not physics:
they only have to rank units against each other for the same job. Physical
facts that cannot be traded off -- "this weapon cannot hit air" -- stay
booleans and are enforced as hard constraints, never as a low number.

    coverage(u, r) = sum_i w_i * c_i(u) / sum_i w_i
    floors(u, r)   = prod_(d, f) min(1, c_d(u) / f) ** 2
    S(u, r)        = coverage * floors      if every hard constraint holds
                   = 0                      otherwise

Both knobs belong to the requirement. A weight says how much a dimension
matters to the job; a floor says the job falls apart below that level, with a
quadratic penalty -- halfway to a floor already costs three quarters of the
score -- so a Siege Tank's firepower cannot buy it a mobile-control score near
a Hellion's. There is no global cut-off: a unit poor at a job scores low and
is taken last, and only one lacking a floored dimension outright, or breaking
a hard constraint, scores zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Capability(Enum):
    """One scalar dimension of `CombatCapabilities`; the value is its field."""

    MOBILITY = "mobility"
    ANTI_GROUND = "anti_ground"
    ANTI_AIR = "anti_air"
    RANGE = "range"
    SIEGE = "siege"
    SPLASH = "splash"
    DURABILITY = "durability"


@dataclass(frozen=True, slots=True)
class CombatCapabilities:
    """One unit type's military profile, every scalar in 0..1.

    mobility     repositioning while staying effective (a Tank that must
                 siege to fight is slow here even at Marine move speed)
    anti_ground  sustained damage against ground targets
    anti_air     sustained damage against air targets
    range        engaging from beyond the typical enemy's reach
    siege        holding a position against superior numbers once set up
    splash       damage against clumped targets
    durability   how much punishment one unit absorbs
    """

    mobility: float
    anti_ground: float
    anti_air: float
    range: float
    siege: float
    splash: float
    durability: float
    attacks_ground: bool
    attacks_air: bool
    is_flying: bool = False

    def __post_init__(self) -> None:
        for capability in Capability:
            if not 0.0 <= self.value_of(capability) <= 1.0:
                raise ValueError(f"{capability.value} must be between 0 and 1")
        if self.anti_ground > 0.0 and not self.attacks_ground:
            raise ValueError("anti_ground requires attacks_ground")
        if self.anti_air > 0.0 and not self.attacks_air:
            raise ValueError("anti_air requires attacks_air")

    def value_of(self, capability: Capability) -> float:
        return float(getattr(self, capability.value))


@dataclass(frozen=True, slots=True)
class Suitability:
    """How well one unit type fits one requirement, with the reason."""

    score: float
    coverage: float
    floor_factor: float
    rejection: str | None = None

    @property
    def admitted(self) -> bool:
        """Physically able to do the job, and worth more than nothing at it."""

        return self.rejection is None

    def log_fields(self) -> dict[str, Any]:
        fields_: dict[str, Any] = {
            "suitability": round(self.score, 3),
            "coverage": round(self.coverage, 3),
            "floor_factor": round(self.floor_factor, 3),
        }
        if self.rejection is not None:
            fields_["rejection"] = self.rejection
        return fields_


REJECTED_NO_PROFILE = Suitability(0.0, 0.0, 0.0, "no_capability_profile")


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    """The capability profile a job wants from the units doing it.

    Scalar fields are importance weights (any non-negative scale; they are
    normalized), ``floors`` are soft minimums and ``requires_*`` hard ones.
    """

    name: str
    mobility: float = 0.0
    anti_ground: float = 0.0
    anti_air: float = 0.0
    range: float = 0.0
    siege: float = 0.0
    splash: float = 0.0
    durability: float = 0.0
    floors: tuple[tuple[Capability, float], ...] = ()
    requires_anti_ground: bool = False
    requires_anti_air: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be blank")
        weights = [self.weight_of(capability) for capability in Capability]
        if any(weight < 0.0 for weight in weights):
            raise ValueError("capability weights must not be negative")
        if sum(weights) <= 0.0:
            raise ValueError("at least one capability weight must be positive")
        if any(not 0.0 < floor <= 1.0 for _, floor in self.floors):
            raise ValueError("floors must be within (0, 1]")
        if len({capability for capability, _ in self.floors}) != len(self.floors):
            raise ValueError("each capability may have at most one floor")

    def weight_of(self, capability: Capability) -> float:
        return float(getattr(self, capability.value))

    def assess(self, capabilities: CombatCapabilities) -> Suitability:
        coverage = sum(
            self.weight_of(capability) * capabilities.value_of(capability)
            for capability in Capability
        ) / sum(self.weight_of(capability) for capability in Capability)
        floor_factor = 1.0
        for capability, floor in self.floors:
            floor_factor *= min(1.0, capabilities.value_of(capability) / floor) ** 2
        score = coverage * floor_factor
        rejection = self._hard_constraint_violation(capabilities)
        if rejection is None and score <= 0.0:
            rejection = self._zero_score_reason(capabilities)
        return Suitability(
            score=score if rejection is None else 0.0,
            coverage=coverage,
            floor_factor=floor_factor,
            rejection=rejection,
        )

    def _hard_constraint_violation(
        self, capabilities: CombatCapabilities
    ) -> str | None:
        if not (capabilities.attacks_ground or capabilities.attacks_air):
            return "cannot_attack"
        if self.requires_anti_ground and not capabilities.attacks_ground:
            return "cannot_attack_ground"
        if self.requires_anti_air and not capabilities.attacks_air:
            return "cannot_attack_air"
        return None

    def _zero_score_reason(self, capabilities: CombatCapabilities) -> str:
        for capability, _floor in self.floors:
            if capabilities.value_of(capability) <= 0.0:
                return f"lacks_{capability.value}"
        return "lacks_every_weighted_capability"

from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.engine.economy.models import ResourceCost

from ..composition import CompositionDoctrine


@dataclass(frozen=True, slots=True)
class ArmyUnitGoal:
    """One member of a desired army composition.

    ``weight`` is a count ratio, not a terminal count: the composition is
    scaled up until it would reach ``MacroGoalSet.army_supply_target``, so a
    member's ``minimum`` is a floor for early-game usefulness and never a
    reason to stop producing (see ``production.army_demand``).
    """

    unit_type: UnitTypeId
    weight: int
    minimum: int
    cost: ResourceCost
    priority_offset: int = 0

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError("army composition weight must be positive")
        if self.minimum < 0:
            raise ValueError("army minimum must not be negative")
        if not -100 <= self.priority_offset <= 100:
            raise ValueError("priority_offset must be between -100 and 100")


@dataclass(frozen=True, slots=True)
class ProductionGoal:
    """A production floor that can scale with sustained collection rates."""

    structure_type: UnitTypeId
    minimum: int
    maximum: int
    cost: ResourceCost
    mineral_rate_for_first_extra: float | None = None
    mineral_rate_per_extra: float = 0.0
    vespene_rate_for_first_extra: float | None = None
    vespene_rate_per_extra: float = 0.0
    minimum_utilization: float = 0.75
    # ``(townhalls, minimum)`` pairs: a build's own "with the third base, add
    # two Factories" timing. Townhalls count the one under construction, so
    # the structures go down with the base rather than after it.
    townhall_minimums: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        if self.minimum < 0 or self.maximum < self.minimum:
            raise ValueError("production counts must satisfy 0 <= minimum <= maximum")
        for townhalls, minimum in self.townhall_minimums:
            if townhalls <= 0:
                raise ValueError("townhall_minimums townhall counts must be positive")
            if not self.minimum <= minimum <= self.maximum:
                raise ValueError(
                    "townhall_minimums must lie between minimum and maximum"
                )
        for value in (
            self.mineral_rate_for_first_extra,
            self.vespene_rate_for_first_extra,
        ):
            if value is not None and value < 0.0:
                raise ValueError("income thresholds must not be negative")
        if self.mineral_rate_per_extra < 0.0 or self.vespene_rate_per_extra < 0.0:
            raise ValueError("income increments must not be negative")
        if not 0.0 <= self.minimum_utilization <= 1.0:
            raise ValueError("minimum_utilization must be between zero and one")

    def minimum_for(self, townhalls: int) -> int:
        """The floor with this many townhalls, never below ``minimum``."""

        return max(
            (
                minimum
                for threshold, minimum in self.townhall_minimums
                if townhalls >= threshold
            ),
            default=self.minimum,
        )

    def target_for_income(self, *, minerals: float, vespene: float) -> int:
        """Return a bounded target; either resource stream may demand capacity."""

        extra = 0
        extra = max(
            extra,
            self._extras_for_rate(
                minerals,
                threshold=self.mineral_rate_for_first_extra,
                increment=self.mineral_rate_per_extra,
            ),
        )
        extra = max(
            extra,
            self._extras_for_rate(
                vespene,
                threshold=self.vespene_rate_for_first_extra,
                increment=self.vespene_rate_per_extra,
            ),
        )
        return min(self.maximum, self.minimum + extra)

    @staticmethod
    def _extras_for_rate(
        rate: float,
        *,
        threshold: float | None,
        increment: float,
    ) -> int:
        if threshold is None or rate < threshold:
            return 0
        if increment <= 0.0:
            return 1
        return 1 + int((rate - threshold) // increment)


@dataclass(frozen=True, slots=True)
class UpgradeGoal:
    """A declared convergence goal.

    Upgrade observation is intentionally not guessed from unit snapshots.  A
    planner can start emitting these as soon as Attention exposes completed
    and pending upgrades.
    """

    upgrade_id: UpgradeId
    cost: ResourceCost


@dataclass(frozen=True, slots=True)
class MacroGoalSet:
    """Configurable post-opening convergence goals for one strategy.

    Concrete instances (one per opening) live in ``profiles.py``,
    kept separate so this file doesn't grow with every new opening.
    """

    name: str
    opening_name: str
    max_workers: int
    max_townhalls: int
    workers_per_townhall: int
    refineries_per_townhall: int
    max_refineries: int
    army_supply_target: float
    army: tuple[ArmyUnitGoal, ...]
    production: tuple[ProductionGoal, ...]
    # The composition this goal set buys within: every army member belongs
    # to it.
    doctrine: CompositionDoctrine
    addons: tuple[tuple[UnitTypeId, int, ResourceCost], ...] = ()
    upgrades: tuple[UpgradeGoal, ...] = ()

    def __post_init__(self) -> None:
        outside = sorted(
            goal.unit_type.name
            for goal in self.army
            if not self.doctrine.includes(goal.unit_type)
        )
        if outside:
            raise ValueError(
                f"army goals outside the {self.doctrine.name} doctrine: "
                + ", ".join(outside)
            )
        if not self.name.strip() or not self.opening_name.strip():
            raise ValueError("strategy and opening names must not be empty")
        if self.max_workers <= 0 or self.max_townhalls <= 0:
            raise ValueError("worker and townhall limits must be positive")
        if self.workers_per_townhall <= 0:
            raise ValueError("workers_per_townhall must be positive")
        if self.refineries_per_townhall < 0 or self.max_refineries < 0:
            raise ValueError("refinery goals must not be negative")
        if self.army_supply_target <= 0.0:
            raise ValueError("army_supply_target must be positive")
        army_types = tuple(goal.unit_type for goal in self.army)
        if len(set(army_types)) != len(army_types):
            raise ValueError("army unit goals must be unique")
        production_types = tuple(goal.structure_type for goal in self.production)
        if len(set(production_types)) != len(production_types):
            raise ValueError("production goals must be unique")
        for _addon, target, _cost in self.addons:
            if target < 0:
                raise ValueError("addon targets must not be negative")

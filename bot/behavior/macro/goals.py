from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.engine.economy.models import ResourceCost


@dataclass(frozen=True, slots=True)
class ArmyUnitGoal:
    """One member of a desired army composition.

    ``weight`` is a count ratio, rather than a hard terminal count.  The
    planner continually looks a small distance ahead and fills the largest
    composition deficits until ``army_supply_target`` is reached.
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

    def __post_init__(self) -> None:
        if self.minimum < 0 or self.maximum < self.minimum:
            raise ValueError("production counts must satisfy 0 <= minimum <= maximum")
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
    """Configurable post-opening convergence goals for one strategy."""

    name: str
    opening_name: str
    max_workers: int
    max_townhalls: int
    workers_per_townhall: int
    refineries_per_townhall: int
    max_refineries: int
    army_supply_target: float
    composition_lookahead: int
    army: tuple[ArmyUnitGoal, ...]
    production: tuple[ProductionGoal, ...]
    addons: tuple[tuple[UnitTypeId, int, ResourceCost], ...] = ()
    upgrades: tuple[UpgradeGoal, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.opening_name.strip():
            raise ValueError("strategy and opening names must not be empty")
        if self.max_workers <= 0 or self.max_townhalls <= 0:
            raise ValueError("worker and townhall limits must be positive")
        if self.workers_per_townhall <= 0:
            raise ValueError("workers_per_townhall must be positive")
        if self.refineries_per_townhall < 0 or self.max_refineries < 0:
            raise ValueError("refinery goals must not be negative")
        if self.army_supply_target <= 0.0 or self.composition_lookahead <= 0:
            raise ValueError("army horizon settings must be positive")
        army_types = tuple(goal.unit_type for goal in self.army)
        if len(set(army_types)) != len(army_types):
            raise ValueError("army unit goals must be unique")
        production_types = tuple(goal.structure_type for goal in self.production)
        if len(set(production_types)) != len(production_types):
            raise ValueError("production goals must be unique")
        for _addon, target, _cost in self.addons:
            if target < 0:
                raise ValueError("addon targets must not be negative")


def bio_three_one_one() -> MacroGoalSet:
    """The initial dynamic macro profile after the Bio 3-1-1 opening.

    The returned frozen value is safe to replace with ``dataclasses.replace``
    in matchup-specific configuration or tests.
    """

    return MacroGoalSet(
        name="bio_three_one_one",
        opening_name="BioThreeOneOne",
        max_workers=70,
        max_townhalls=4,
        workers_per_townhall=22,
        refineries_per_townhall=2,
        max_refineries=8,
        army_supply_target=115.0,
        composition_lookahead=8,
        army=(
            ArmyUnitGoal(
                UnitTypeId.MARINE,
                weight=8,
                minimum=12,
                cost=ResourceCost(minerals=50, supply=1.0),
            ),
            ArmyUnitGoal(
                UnitTypeId.MARAUDER,
                weight=3,
                minimum=4,
                cost=ResourceCost(minerals=100, vespene=25, supply=2.0),
            ),
            ArmyUnitGoal(
                UnitTypeId.MEDIVAC,
                weight=2,
                minimum=2,
                cost=ResourceCost(minerals=100, vespene=100, supply=2.0),
                priority_offset=2,
            ),
            ArmyUnitGoal(
                UnitTypeId.SIEGETANK,
                weight=2,
                minimum=2,
                cost=ResourceCost(minerals=150, vespene=125, supply=3.0),
            ),
        ),
        production=(
            ProductionGoal(
                UnitTypeId.BARRACKS,
                minimum=3,
                maximum=8,
                cost=ResourceCost(minerals=150),
                mineral_rate_for_first_extra=1_200.0,
                mineral_rate_per_extra=500.0,
            ),
            ProductionGoal(
                UnitTypeId.FACTORY,
                minimum=1,
                maximum=3,
                cost=ResourceCost(minerals=150, vespene=100),
                vespene_rate_for_first_extra=650.0,
                vespene_rate_per_extra=450.0,
            ),
            ProductionGoal(
                UnitTypeId.STARPORT,
                minimum=1,
                maximum=3,
                cost=ResourceCost(minerals=150, vespene=100),
                vespene_rate_for_first_extra=800.0,
                vespene_rate_per_extra=500.0,
            ),
        ),
        addons=(
            (
                UnitTypeId.BARRACKSTECHLAB,
                2,
                ResourceCost(minerals=50, vespene=25),
            ),
            (
                UnitTypeId.FACTORYTECHLAB,
                1,
                ResourceCost(minerals=50, vespene=25),
            ),
            (
                UnitTypeId.STARPORTREACTOR,
                1,
                ResourceCost(minerals=50, vespene=50),
            ),
        ),
        upgrades=(
            UpgradeGoal(
                UpgradeId.STIMPACK,
                ResourceCost(minerals=100, vespene=100),
            ),
            UpgradeGoal(
                UpgradeId.SHIELDWALL,
                ResourceCost(minerals=100, vespene=100),
            ),
            UpgradeGoal(
                UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,
                ResourceCost(minerals=100, vespene=100),
            ),
        ),
    )

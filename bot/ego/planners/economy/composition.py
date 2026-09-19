"""Army baseline, counter adaptation, and emergency production fallback."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from ares.dicts.unit_data import UNIT_DATA
from ares.dicts.unit_tech_requirement import UNIT_TECH_REQUIREMENT
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.ids.unit_typeid import UnitTypeId

from bot.attention import AttentionState
from bot.awareness import Contact, ThreatIncident
from bot.ego.planners import (
    CompositionPlan,
    CounterAdaptation,
    SurvivalComposition,
)
from bot.ego.strategy import EconomyPosture, StrategyState

from .counter_catalog import (
    REACH,
    CounterCatalog,
    can_reach,
    canonical_unit,
    physics_digest,
    target_layers,
)
from .styles import ArmyStyle

TECHLAB_OF = {
    UnitTypeId.BARRACKS: UnitTypeId.BARRACKSTECHLAB,
    UnitTypeId.FACTORY: UnitTypeId.FACTORYTECHLAB,
    UnitTypeId.STARPORT: UnitTypeId.STARPORTTECHLAB,
}


@dataclass(frozen=True, slots=True)
class CompositionConfig:
    # Enemy power, in Marines, that weighs as much as the style baseline.
    prior_power: float = 20.0
    # Included in the run fingerprint so catalog changes identify a new bot.
    catalog_digest: str = ""
    physics_digest: str = ""

    def __post_init__(self) -> None:
        if self.prior_power <= 0.0:
            raise ValueError("prior_power must be positive")
        if not self.catalog_digest or not self.physics_digest:
            raise ValueError("catalog_digest and physics_digest must not be empty")


@lru_cache(maxsize=1)
def default_catalog() -> CounterCatalog:
    return CounterCatalog.load()


class CompositionPlanner:
    def __init__(
        self,
        style: ArmyStyle,
        catalog: CounterCatalog | None = None,
        config: CompositionConfig | None = None,
    ) -> None:
        self.style = style
        self.catalog = catalog or default_catalog()
        self.config = config or CompositionConfig(
            catalog_digest=self.catalog.digest,
            physics_digest=physics_digest(),
        )
        if self.config.catalog_digest != self.catalog.digest:
            raise ValueError("CompositionConfig catalog_digest does not match the catalog")
        if self.config.physics_digest != physics_digest():
            raise ValueError("CompositionConfig physics_digest does not match REACH")
        self._validate_style()

    def plan(
        self,
        attention: AttentionState,
        strategy: StrategyState,
        enemy: Iterable[tuple[UnitTypeId, float]] = (),
        *,
        contacts: Iterable[Contact] = (),
        incidents: Iterable[ThreatIncident] = (),
    ) -> CompositionPlan:
        believed = tuple((type_id, power) for type_id, power in enemy if power > 0.0)
        tech_ready = attention.tech_ready
        baseline_supply = _as_supply(self.style.composition)
        unresolved = 0.0
        response_power: dict[UnitTypeId, float] = {}
        adaptations: list[CounterAdaptation] = []
        selected_order: list[UnitTypeId] = []
        enemies: list[tuple[UnitTypeId, UnitTypeId, float]] = []

        for observed, power in believed:
            canonical = canonical_unit(observed)
            enemies.append((observed, canonical, power))
            counters = self.catalog.counters_for(canonical)
            if counters is None:
                unresolved += power
                adaptations.append(
                    CounterAdaptation(observed, canonical, power, None, status="uncatalogued")
                )
                continue
            if not counters:
                unresolved += power
                adaptations.append(
                    CounterAdaptation(observed, canonical, power, None, status="known_no_counter")
                )
                continue
            skipped: list[tuple[UnitTypeId, str]] = []
            response = None
            for candidate in counters:
                if not can_reach(candidate, observed):
                    skipped.append((candidate, "cannot_reach"))
                    continue
                if candidate in tech_ready:
                    response = candidate
                    break
                skipped.append((candidate, "tech_missing"))
            if response is None:
                unresolved += power
                adaptations.append(
                    CounterAdaptation(
                        observed,
                        canonical,
                        power,
                        None,
                        tuple(skipped),
                        "no_producible_counter",
                    )
                )
                continue
            response_power[response] = response_power.get(response, 0.0) + power
            if response not in selected_order:
                selected_order.append(response)
            adaptations.append(
                CounterAdaptation(observed, canonical, power, response, tuple(skipped), "selected")
            )

        if response_power:
            baseline_mass = self.config.prior_power + unresolved
            supply_mass = {
                unit_type: share * baseline_mass for unit_type, share in baseline_supply.items()
            }
            for response, power in response_power.items():
                supply_mass[response] = supply_mass.get(response, 0.0) + power
            count_shares = _as_count(supply_mass)
            units = self._normal_units(count_shares, selected_order)
        else:
            # Besides avoiding float noise, this guarantees that unknown,
            # known-empty and currently unavailable responses mean baseline.
            units = self.style.composition
        survival = None
        reason = "counter_adaptation" if response_power else "style_baseline"

        if strategy.economy_policy.posture is EconomyPosture.SURVIVE:
            incident = _strongest(tuple(incidents))
            if incident is not None:
                units, survival = self._survival_units(attention, units, incident, tuple(contacts))
                reason = "survival_fallback"

        return CompositionPlan(
            style=self.style.name,
            baseline=self.style.composition,
            enemy=tuple(enemies),
            adaptations=tuple(adaptations),
            survival=survival,
            units=units,
            tech_ready=tuple(sorted(tech_ready, key=lambda item: item.name)),
            reason=reason,
        )

    def _normal_units(
        self, shares: dict[UnitTypeId, float], selected_order: list[UnitTypeId]
    ) -> tuple[tuple[UnitTypeId, float, int], ...]:
        priorities = {unit_type: priority for unit_type, _, priority in self.style.composition}
        fallback_priority = max(priorities.values())
        order = [unit_type for unit_type, _, _ in self.style.composition]
        order.extend(unit_type for unit_type in selected_order if unit_type not in priorities)
        return tuple(
            (
                unit_type,
                shares.get(unit_type, 0.0),
                priorities.get(unit_type, fallback_priority),
            )
            for unit_type in order
            if shares.get(unit_type, 0.0) > 0.0
        )

    def _survival_units(
        self,
        attention: AttentionState,
        normal: tuple[tuple[UnitTypeId, float, int], ...],
        incident: ThreatIncident,
        contacts: tuple[Contact, ...],
    ) -> tuple[tuple[tuple[UnitTypeId, float, int], ...], SurvivalComposition]:
        by_tag = {contact.tag: contact for contact in contacts}
        members = tuple(by_tag[tag] for tag in incident.contacts if tag in by_tag)
        targets = tuple(member.type_id for member in members)
        if targets:

            def reaches_incident(candidate: UnitTypeId) -> bool:
                return any(can_reach(candidate, target) for target in targets)

        else:
            wants_ground = incident.ground_power > 0.0
            wants_air = incident.air_power > 0.0

            def reaches_incident(candidate: UnitTypeId) -> bool:
                return (REACH[candidate][0] and wants_ground) or (REACH[candidate][1] and wants_air)

        ready_producers = {
            structure.type_id for structure in attention.own_structures if structure.is_ready
        }
        universe = self.catalog.response_types | frozenset(
            unit_type for unit_type, _, _ in self.style.composition
        )
        candidates = {
            unit_type
            for unit_type in universe
            if unit_type in attention.tech_ready
            and UNIT_TRAINED_FROM.get(unit_type, set()) & ready_producers
            and REACH.get(unit_type, (False, False)) != (False, False)
            and reaches_incident(unit_type)
        }

        scores = {candidate: 0.0 for candidate in candidates}
        for member in members:
            counters = self.catalog.counters_for(member.type_id) or ()
            weight = member.power * member.confidence
            for rank, response in enumerate(counters):
                if response in candidates:
                    scores[response] += weight / (rank + 1.0)
        style_priority = {unit_type: priority for unit_type, _, priority in self.style.composition}
        ordered = sorted(
            candidates,
            key=lambda unit_type: (
                -scores[unit_type],
                style_priority.get(unit_type, 10),
                unit_type.name,
            ),
        )
        normal_shares = {unit_type: share for unit_type, share, _ in normal}
        all_types = ordered + [
            unit_type for unit_type, _, _ in normal if unit_type not in candidates
        ]
        units = tuple(
            (unit_type, normal_shares.get(unit_type, 0.0), min(index, 10))
            for index, unit_type in enumerate(all_types)
        )
        style_types = frozenset(style_priority)
        added = tuple(
            (
                unit_type,
                "outside_style" if unit_type not in style_types else "ready_capacity",
            )
            for unit_type in ordered
            if unit_type not in normal_shares
        )
        return units, SurvivalComposition(incident.incident_id, added)

    def _validate_style(self) -> None:
        total = sum(share for _, share, _ in self.style.composition)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"style {self.style.name} composition must sum to 1")
        for unit_type, share, priority in self.style.composition:
            if unit_type not in REACH:
                raise ValueError(f"style unit {unit_type.name} has no REACH entry")
            if share <= 0.0:
                raise ValueError(f"style unit {unit_type.name} has a non-positive share")
            if not 0 <= priority <= 10:
                raise ValueError(f"style unit {unit_type.name} has invalid priority")


def reactor_share(mix: Iterable[tuple[UnitTypeId, float, int]], structure: UnitTypeId) -> float:
    """Share of ``structure`` that should carry a Reactor for this count mix."""

    reactor = techlab = 0.0
    for unit_type, share, _ in mix:
        if structure not in UNIT_TRAINED_FROM.get(unit_type, ()):
            continue
        if TECHLAB_OF[structure] in UNIT_TECH_REQUIREMENT.get(unit_type, ()):
            techlab += share
        else:
            reactor += share
    if reactor + techlab <= 0.0:
        return 0.0
    return reactor / (reactor + 2.0 * techlab)


def _as_supply(
    composition: Iterable[tuple[UnitTypeId, float, int]],
) -> dict[UnitTypeId, float]:
    weighted = {
        unit_type: share * float(UNIT_DATA[unit_type]["supply"])
        for unit_type, share, _ in composition
    }
    total = sum(weighted.values())
    return {unit_type: weight / total for unit_type, weight in weighted.items()}


def _as_count(supply_mass: dict[UnitTypeId, float]) -> dict[UnitTypeId, float]:
    weighted = {
        unit_type: mass / float(UNIT_DATA[unit_type]["supply"])
        for unit_type, mass in supply_mass.items()
        if mass > 0.0
    }
    total = sum(weighted.values())
    return {unit_type: weight / total for unit_type, weight in weighted.items()}


def _strongest(incidents: tuple[ThreatIncident, ...]) -> ThreatIncident | None:
    return max(
        incidents,
        key=lambda incident: (incident.threat, incident.power, incident.incident_id),
        default=None,
    )


__all__ = [
    "CompositionConfig",
    "CompositionPlanner",
    "REACH",
    "reactor_share",
    "target_layers",
]

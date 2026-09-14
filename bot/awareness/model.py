"""AWARENESS: what the bot believes about the world beyond this frame.

Enemy contacts are remembered with a confidence that decays with age,
``exp(-age / tau)``, and a position uncertainty that grows with it. A contact
is forgotten when it is confirmed dead, when its last position is back in
vision without it, or once its confidence has faded out. From those beliefs
Awareness reads the pressure on each of our bases and a coarse influence field.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, BaseView, UnitView

from .field import InfluenceField, Source, build_field


@dataclass(frozen=True, slots=True)
class AwarenessConfig:
    # tau of a contact's confidence; structures do not walk away.
    unit_memory: float = 20.0
    structure_memory: float = 240.0
    forget_below: float = 0.05
    # A hidden contact's last position must stay out of sight this long before
    # the empty spot counts: a unit that just left vision is still beside it.
    vision_grace: float = 2.0
    # How far an unseen unit may have walked per second, up to a cap.
    drift_speed: float = 2.8
    max_uncertainty: float = 16.0
    # How an attacker's pressure spreads around a base, and how far it reaches.
    base_sigma: float = 14.0
    base_reach: float = 30.0
    # Power, in Marines, whose pressure saturates to 1 - 1/e.
    full_pressure: float = 4.0
    field_sigma: float = 7.0
    # Presence a structure lends the field, in Marines.
    structure_presence: float = 0.5

    def __post_init__(self) -> None:
        for name in (
            "unit_memory",
            "structure_memory",
            "drift_speed",
            "base_sigma",
            "base_reach",
            "full_pressure",
            "field_sigma",
        ):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if not 0.0 < self.forget_below < 1.0:
            raise ValueError("forget_below must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class Contact:
    tag: int
    type_id: UnitTypeId
    position: Point2
    power: float
    is_flying: bool
    is_structure: bool
    is_worker: bool
    last_seen: float
    visible: bool
    confidence: float
    uncertainty: float


@dataclass(frozen=True, slots=True)
class BaseThreat:
    base_id: str
    position: Point2
    is_main: bool
    # sum(power * confidence * K) of the attackers in reach.
    pressure: float
    # sum(power * K) of our own army in reach.
    cover: float
    # S(pressure / full_pressure)
    threat: float
    # Share of the pressure that flies.
    air_share: float
    # Pressure-weighted position of the attack; None without pressure.
    center: Point2 | None

    @property
    def balance(self) -> float:
        """The attack's share of everything at the base, in [0, 1]."""

        total = self.pressure + self.cover
        return self.pressure / total if self.pressure > 0.0 else 0.0


@dataclass(frozen=True, slots=True)
class AwarenessState:
    time: float
    contacts: tuple[Contact, ...]
    bases: tuple[BaseThreat, ...]
    own_power: float
    enemy_power: float
    influence: InfluenceField = field(compare=False)

    @property
    def danger(self) -> float:
        return max((base.threat for base in self.bases), default=0.0)

    @property
    def most_threatened(self) -> BaseThreat | None:
        threatened = [base for base in self.bases if base.pressure > 0.0]
        if not threatened:
            return None
        return max(threatened, key=lambda base: (base.threat, base.base_id))

    def base(self, base_id: str) -> BaseThreat | None:
        return next((base for base in self.bases if base.base_id == base_id), None)


class AwarenessModel:
    def __init__(self, config: AwarenessConfig | None = None) -> None:
        self.config = config or AwarenessConfig()
        self._contacts: dict[int, Contact] = {}
        self._lattice: tuple[Point2, ...] | None = None
        self._xs = np.zeros(0)
        self._ys = np.zeros(0)

    def infer(self, attention: AttentionState) -> AwarenessState:
        contacts = self._remember(attention)
        army = tuple(
            unit for unit in attention.own_units if not unit.is_worker and unit.power > 0.0
        )
        return AwarenessState(
            time=attention.time,
            contacts=contacts,
            bases=tuple(self._base_threat(base, contacts, army) for base in attention.bases),
            own_power=sum(unit.power for unit in army),
            enemy_power=sum(
                contact.power * contact.confidence
                for contact in contacts
                if not contact.is_structure
            ),
            influence=self._field(attention, contacts, army),
        )

    def _remember(self, attention: AttentionState) -> tuple[Contact, ...]:
        config = self.config
        now = attention.time
        remembered: dict[int, Contact] = {}
        for unit in (*attention.enemy_units, *attention.enemy_structures):
            remembered[unit.tag] = Contact(
                tag=unit.tag,
                type_id=unit.type_id,
                position=unit.position,
                power=unit.power,
                is_flying=unit.is_flying,
                is_structure=unit.is_structure,
                is_worker=unit.is_worker,
                last_seen=now,
                visible=True,
                confidence=1.0,
                uncertainty=0.0,
            )
        for tag, previous in self._contacts.items():
            if tag in remembered or tag in attention.dead_tags:
                continue
            age = max(0.0, now - previous.last_seen)
            memory = config.structure_memory if previous.is_structure else config.unit_memory
            confidence = math.exp(-age / memory)
            if confidence < config.forget_below:
                continue
            if age >= config.vision_grace and attention.is_visible(previous.position):
                continue
            remembered[tag] = replace(
                previous,
                visible=False,
                confidence=confidence,
                uncertainty=(
                    0.0
                    if previous.is_structure
                    else min(config.max_uncertainty, config.drift_speed * age)
                ),
            )
        self._contacts = remembered
        return tuple(remembered[tag] for tag in sorted(remembered))

    def _base_threat(
        self, base: BaseView, contacts: tuple[Contact, ...], army: tuple[UnitView, ...]
    ) -> BaseThreat:
        config = self.config
        bx, by = base.position.x, base.position.y
        pressure = air = weighted_x = weighted_y = 0.0
        for contact in contacts:
            if contact.power <= 0.0:
                continue
            squared = (contact.position.x - bx) ** 2 + (contact.position.y - by) ** 2
            if squared > (config.base_reach + contact.uncertainty) ** 2:
                continue
            spread = config.base_sigma + contact.uncertainty
            weight = (
                contact.power * contact.confidence * math.exp(-0.5 * squared / (spread * spread))
            )
            pressure += weight
            weighted_x += weight * contact.position.x
            weighted_y += weight * contact.position.y
            if contact.is_flying:
                air += weight
        cover = 0.0
        for unit in army:
            squared = (unit.position.x - bx) ** 2 + (unit.position.y - by) ** 2
            if squared <= config.base_reach**2:
                cover += unit.power * math.exp(
                    -0.5 * squared / (config.base_sigma * config.base_sigma)
                )
        return BaseThreat(
            base_id=base.base_id,
            position=base.position,
            is_main=base.is_main,
            pressure=pressure,
            cover=cover,
            threat=1.0 - math.exp(-pressure / config.full_pressure),
            air_share=air / pressure if pressure > 0.0 else 0.0,
            center=(
                Point2((weighted_x / pressure, weighted_y / pressure)) if pressure > 0.0 else None
            ),
        )

    def _field(
        self,
        attention: AttentionState,
        contacts: tuple[Contact, ...],
        army: tuple[UnitView, ...],
    ) -> InfluenceField:
        config = self.config
        lattice = attention.map.lattice
        if lattice is not self._lattice:
            self._lattice = lattice
            self._xs = np.array([point.x for point in lattice], dtype=float)
            self._ys = np.array([point.y for point in lattice], dtype=float)
        full = config.full_pressure
        sigma = config.field_sigma
        fighters = [contact for contact in contacts if contact.power > 0.0]
        return build_field(
            lattice,
            attention.map.lattice_spacing,
            self._xs,
            self._ys,
            threat=[
                Source(
                    c.position.x, c.position.y, c.power * c.confidence / full, sigma + c.uncertainty
                )
                for c in fighters
            ],
            support=[
                *(Source(u.position.x, u.position.y, u.power / full, sigma) for u in army),
                *(
                    Source(s.position.x, s.position.y, config.structure_presence / full, sigma)
                    for s in attention.own_structures
                ),
            ],
            enemy=[
                *(
                    Source(c.position.x, c.position.y, c.power * c.confidence / full, sigma)
                    for c in fighters
                ),
                *(
                    Source(
                        c.position.x,
                        c.position.y,
                        config.structure_presence * c.confidence / full,
                        sigma,
                    )
                    for c in contacts
                    if c.is_structure
                ),
            ],
        )

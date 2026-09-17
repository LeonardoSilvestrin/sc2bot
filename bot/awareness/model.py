"""AWARENESS: what the bot believes about the world beyond this frame.

Enemy contacts are remembered with a confidence that decays with age,
``exp(-age / tau)``, and a position uncertainty that grows with it. A contact
is forgotten when it is confirmed dead, when its last position is back in
vision without it, or once its confidence has faded out. From those beliefs
Awareness reads the pressure on each of our bases, the threat incidents -- the
attackers in reach of our bases that belong together -- and a coarse influence
field.

The enemy army is believed to exist far longer than it is believed to be where
it was seen: a unit seen alive and not seen die fades with ``army_memory``, and
an enemy never seen is still expected to have an army that grows with game
time. The estimate is the larger of the two; the part of it no contact places
is its uncertainty.

A contact remembers whether it was cloaked or burrowed, and whether nothing
could shoot it when last seen; Awareness also remembers when an enemy army unit
was first seen cloaked.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, BaseView, UnitView, is_army

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
    # Attackers within this distance of one another are one incident.
    incident_link: float = 12.0
    # tau of a base's remembered threat: an attack that thins out or steps back
    # is still believed for a while, and a stronger one counts at once.
    threat_memory: float = 20.0
    # tau of the belief that an enemy army unit seen alive, and not seen die,
    # still exists: an army does not vanish into the fog, but a unit can die
    # unseen or run out of timed life.
    army_memory: float = 180.0
    # The army, in Marines, expected of an enemy with no sighting: it grows
    # this much per second from `army_onset` on, up to `army_cap`.
    army_growth: float = 0.1
    army_onset: float = 120.0
    army_cap: float = 100.0
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
            "incident_link",
            "threat_memory",
            "field_sigma",
        ):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if not 0.0 < self.forget_below < 1.0:
            raise ValueError("forget_below must be between 0 and 1")
        # Otherwise a contact could place more of the army than is believed alive.
        if self.army_memory < self.unit_memory:
            raise ValueError("army_memory must not be shorter than unit_memory")
        for name in ("army_growth", "army_onset", "army_cap"):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must not be negative")


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
    # Cloaked or burrowed when last seen, detected or not.
    is_cloaked: bool = False
    # ... and undetected: nothing could shoot it.
    is_hidden: bool = False


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
    # max(threat, last recent_threat * exp(-dt / threat_memory)); the faded part
    # is forgotten below forget_below.
    recent_threat: float
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
class ThreatIncident:
    """Attackers in reach of our bases chained within `incident_link` of one
    another, however many bases they reach.

    The id is the lowest member tag, so it holds while that contact stays in
    the incident. When an incident splits, the part without that contact takes
    its own lowest tag; when incidents merge, the lowest tag of all wins.
    """

    incident_id: str
    # Member contact tags, ascending.
    contacts: tuple[int, ...]
    # sum(power * confidence) of the members on the ground and in the air.
    ground_power: float
    air_power: float
    # Mean confidence of the members, weighted by power.
    confidence: float
    # (power * confidence)-weighted position of the members.
    center: Point2
    # (base_id, sum(power * confidence * K) of the members) for every base a
    # member is in reach of, by base id.
    pressure_by_base: tuple[tuple[str, float], ...]
    # S(pressure on the base it presses hardest / full_pressure)
    threat: float

    @property
    def power(self) -> float:
        return self.ground_power + self.air_power

    @property
    def pressure(self) -> float:
        return max((pressure for _, pressure in self.pressure_by_base), default=0.0)

    @property
    def affected_bases(self) -> tuple[str, ...]:
        return tuple(base_id for base_id, _ in self.pressure_by_base)


@dataclass(frozen=True, slots=True)
class AwarenessState:
    time: float
    contacts: tuple[Contact, ...]
    bases: tuple[BaseThreat, ...]
    own_power: float
    # sum(power * confidence) of the remembered enemy army: the part of it a
    # contact still places. Workers and structures are no army.
    enemy_power: float
    influence: InfluenceField = field(compare=False)
    # By lowest member tag.
    incidents: tuple[ThreatIncident, ...] = ()
    # sum(power * exp(-age / army_memory)) of the enemy army units seen alive
    # and not seen die.
    seen_enemy_power: float = 0.0
    # The army an enemy is expected to have by now without any sighting.
    expected_enemy_power: float = 0.0
    # When an enemy army unit was first seen cloaked or burrowed; None before.
    cloak_seen_at: float | None = None

    @property
    def estimated_enemy_power(self) -> float:
        """The enemy army believed to exist: everything seen alive, and never
        less than an enemy is expected to have by now."""

        return max(self.enemy_power, self.seen_enemy_power, self.expected_enemy_power)

    @property
    def enemy_uncertainty(self) -> float:
        """The part of the estimate no contact places."""

        return self.estimated_enemy_power - self.enemy_power

    @property
    def enemy_coverage(self) -> float:
        """The share of the estimate a contact places; 1 while nothing is believed."""

        estimated = self.estimated_enemy_power
        return self.enemy_power / estimated if estimated > 0.0 else 1.0

    @property
    def hidden_contacts(self) -> tuple[Contact, ...]:
        """Enemy units in sight now that nothing can shoot, by tag."""

        return tuple(
            contact
            for contact in self.contacts
            if contact.visible and contact.is_hidden and not contact.is_structure
        )

    @property
    def danger(self) -> float:
        """The most any base is remembered threatened."""

        return max((base.recent_threat for base in self.bases), default=0.0)

    @property
    def danger_now(self) -> float:
        return max((base.threat for base in self.bases), default=0.0)

    @property
    def most_threatened(self) -> BaseThreat | None:
        threatened = [base for base in self.bases if base.recent_threat > 0.0]
        if not threatened:
            return None
        return max(threatened, key=lambda base: (base.recent_threat, base.base_id))

    def base(self, base_id: str) -> BaseThreat | None:
        return next((base for base in self.bases if base.base_id == base_id), None)


class AwarenessModel:
    def __init__(self, config: AwarenessConfig | None = None) -> None:
        self.config = config or AwarenessConfig()
        self._contacts: dict[int, Contact] = {}
        # (time, recent_threat) by base id.
        self._threats: dict[str, tuple[float, float]] = {}
        # (last seen, power) of every enemy army unit believed alive, by tag.
        self._army: dict[int, tuple[float, float]] = {}
        self._cloak_seen_at: float | None = None
        self._lattice: tuple[Point2, ...] | None = None
        self._xs = np.zeros(0)
        self._ys = np.zeros(0)

    def infer(self, attention: AttentionState) -> AwarenessState:
        config = self.config
        contacts = self._remember(attention)
        seen_enemy = self._remember_army(attention)
        if self._cloak_seen_at is None and any(
            unit.is_cloaked and is_army(unit) for unit in attention.enemy_units
        ):
            self._cloak_seen_at = attention.time
        army = tuple(
            unit for unit in attention.own_units if not unit.is_worker and unit.power > 0.0
        )
        bases = tuple(self._base_threat(base, contacts, army) for base in attention.bases)
        return AwarenessState(
            time=attention.time,
            contacts=contacts,
            bases=self._remember_threats(attention.time, bases),
            own_power=sum(unit.power for unit in army),
            # The army memory outlasts every contact of an army unit.
            enemy_power=sum(
                contact.power * contact.confidence
                for contact in contacts
                if contact.tag in self._army
            ),
            influence=self._field(attention, contacts, army),
            incidents=self._incidents(attention.bases, contacts),
            seen_enemy_power=seen_enemy,
            expected_enemy_power=min(
                config.army_cap,
                config.army_growth * max(0.0, attention.time - config.army_onset),
            ),
            cloak_seen_at=self._cloak_seen_at,
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
                is_cloaked=unit.is_cloaked,
                is_hidden=unit.is_hidden,
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

    def _remember_army(self, attention: AttentionState) -> float:
        """sum(power * exp(-age / army_memory)) of the enemy army units seen
        alive and not seen die, wherever they went since."""

        config = self.config
        now = attention.time
        army = {tag: seen for tag, seen in self._army.items() if tag not in attention.dead_tags}
        for unit in attention.enemy_units:
            if is_army(unit) and unit.power > 0.0:
                army[unit.tag] = (now, unit.power)
        self._army = {}
        power = 0.0
        for tag in sorted(army):
            seen_at, unit_power = army[tag]
            existence = math.exp(-max(0.0, now - seen_at) / config.army_memory)
            if existence < config.forget_below:
                continue
            self._army[tag] = army[tag]
            power += unit_power * existence
        return power

    def _pressure(self, contact: Contact, position: Point2) -> float | None:
        """power * confidence * K of a contact at a base; None beyond its reach."""

        config = self.config
        squared = (contact.position.x - position.x) ** 2 + (contact.position.y - position.y) ** 2
        if squared > (config.base_reach + contact.uncertainty) ** 2:
            return None
        spread = config.base_sigma + contact.uncertainty
        return contact.power * contact.confidence * math.exp(-0.5 * squared / (spread * spread))

    def _base_threat(
        self, base: BaseView, contacts: tuple[Contact, ...], army: tuple[UnitView, ...]
    ) -> BaseThreat:
        config = self.config
        bx, by = base.position.x, base.position.y
        pressure = air = weighted_x = weighted_y = 0.0
        for contact in contacts:
            if contact.power <= 0.0:
                continue
            weight = self._pressure(contact, base.position)
            if weight is None:
                continue
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
            # Until `_remember_threats` adds what the base remembers.
            recent_threat=1.0 - math.exp(-pressure / config.full_pressure),
            air_share=air / pressure if pressure > 0.0 else 0.0,
            center=(
                Point2((weighted_x / pressure, weighted_y / pressure)) if pressure > 0.0 else None
            ),
        )

    def _remember_threats(
        self, now: float, bases: tuple[BaseThreat, ...]
    ) -> tuple[BaseThreat, ...]:
        """Each base's threat, held against its own fading memory of the last frames."""

        config = self.config
        remembered: list[BaseThreat] = []
        threats: dict[str, tuple[float, float]] = {}
        for base in bases:
            then, last = self._threats.get(base.base_id, (now, 0.0))
            faded = last * math.exp(-max(0.0, now - then) / config.threat_memory)
            if faded < config.forget_below:
                faded = 0.0
            recent = max(base.threat, faded)
            threats[base.base_id] = (now, recent)
            remembered.append(replace(base, recent_threat=recent))
        # A base that is gone takes its memory with it.
        self._threats = threats
        return tuple(remembered)

    def _incidents(
        self, bases: tuple[BaseView, ...], contacts: tuple[Contact, ...]
    ) -> tuple[ThreatIncident, ...]:
        """Single-link groups of the attackers in reach of some base."""

        members: list[Contact] = []
        pressures: list[tuple[float | None, ...]] = []
        for contact in contacts:
            if contact.power <= 0.0:
                continue
            at_bases = tuple(self._pressure(contact, base.position) for base in bases)
            if any(pressure is not None for pressure in at_bases):
                members.append(contact)
                pressures.append(at_bases)
        if not members:
            return ()
        xy = np.array([(member.position.x, member.position.y) for member in members])
        squared = ((xy[:, None, :] - xy[None, :, :]) ** 2).sum(axis=2)
        linked = squared <= self.config.incident_link**2
        group = np.full(len(members), -1)
        incidents: list[ThreatIncident] = []
        # Contacts come by tag, so every group is seeded by its lowest tag.
        for seed in range(len(members)):
            if group[seed] >= 0:
                continue
            group[seed] = seed
            frontier = [seed]
            while frontier:
                joined = np.flatnonzero(linked[frontier.pop()] & (group < 0))
                group[joined] = seed
                frontier.extend(joined.tolist())
            indices = np.flatnonzero(group == seed).tolist()
            incidents.append(
                self._incident(
                    [members[index] for index in indices],
                    [pressures[index] for index in indices],
                    bases,
                )
            )
        return tuple(incidents)

    def _incident(
        self,
        members: list[Contact],
        pressures: list[tuple[float | None, ...]],
        bases: tuple[BaseView, ...],
    ) -> ThreatIncident:
        weights = [member.power * member.confidence for member in members]
        total = sum(weights)
        pressure_by_base = tuple(
            (
                base.base_id,
                sum(at_bases[index] for at_bases in pressures if at_bases[index] is not None),
            )
            for index, base in enumerate(bases)
            if any(at_bases[index] is not None for at_bases in pressures)
        )
        strongest = max(pressure for _, pressure in pressure_by_base)
        return ThreatIncident(
            incident_id=f"incident:{members[0].tag}",
            contacts=tuple(member.tag for member in members),
            ground_power=sum(
                weight
                for member, weight in zip(members, weights, strict=True)
                if not member.is_flying
            ),
            air_power=sum(
                weight for member, weight in zip(members, weights, strict=True) if member.is_flying
            ),
            confidence=total / sum(member.power for member in members),
            center=Point2(
                (
                    sum(w * m.position.x for m, w in zip(members, weights, strict=True)) / total,
                    sum(w * m.position.y for m, w in zip(members, weights, strict=True)) / total,
                )
            ),
            pressure_by_base=pressure_by_base,
            threat=1.0 - math.exp(-strongest / self.config.full_pressure),
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

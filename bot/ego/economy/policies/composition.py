"""Army composition: the mix that fights the enemy army believed in best.

THE BELIEF. Awareness remembers two things by type: the enemy army seen
alive and not seen die, S_e Marines of power (S in all), and what the enemy
has been seen to build, dead or alive, H_e (H in all). The first is what is
there now; the second is what the enemy makes, and outlives a won fight: a
Lurker killed still says there is a Lurker Den. The observer
(`bot.awareness.enemy_army`) believes in more army than was seen. What the
unseen part is made of is the Dirichlet posterior mean of the enemy's
production shares,

    m_e = (H_e + P r_e) / (H + P)        r: the race's prior (knowledge/combat.yml)

with P = `prior_power` Marines of weight. The army believed in is
A = max(S, mu + k sigma) and its unseen part U = A - S. The share of type e,
counting P as army that may always be out of sight:

    w_e = (S_e + (U + P) m_e) / (S + U + P)

THE VALUE OF A UNIT. By Lanchester's square law a force of n units fights as
n sqrt(dps * hit points). Per resource spent, our type i is worth against e

    k_ie = a_i sqrt(dps(i, e) T_i) / cost_i
    T_i  = hp_i / sum_e (w_e / power_e) dps(e, i)

T_i is how long i lasts under the believed enemy army's fire, per Marine of
it; dps comes from the combat model (`knowledge.combat`), bonuses, armor and
splash included. a_i = exp(-delay_i / tech_horizon) discounts a unit whose
tech is still to be built by the time that takes.

THE MIX. The army's resources x, a share per combat type, maximize

    J(x) = H sum_e w_e log(sum_i x_i k_ie) + D sum_i b_i log x_i

The first term is the log-optimal portfolio against the enemy: at its optimum
each enemy type e takes a share w_e of our resources, spent on the units that
answer it in proportion to how much of the answer they are. No enemy type can
be left unanswered (log 0), and no unit is chosen by rank: a slightly better
unit gets slightly more. The second term is the style's doctrine b (the
style's composition, in resources) as a prior worth D = `doctrine_power`
Marines of enemy production seen: with nothing seen the mix is the style, and
the more of what the enemy builds is seen the more the enemy decides. J is
concave, and its maximum is the fixed point of

    x_i <- (H x_i sum_e w_e k_ie / (K x)_e + D b_i) / (H + D)

which each step climbs (the EM update of mixture weights under a Dirichlet
prior). The target is a ratio; Ares' SpawnController closes the loop on it,
training whichever type is short of its share, counting what is in
production.

A support unit with no weapon (the Medivac) cannot be priced by damage: it
keeps its share of the style's resources.

TECH. Ares' ProductionController builds the tech of every unit in the
composition. A unit enters the composition only with at least `min_share` of
the army: below that Ares would neither add production for it nor field more
than a token of it, and a unit whose tech is missing would have it bought for
that token.

THE STYLE. Its composition is the doctrine; the mix may also use the types
the style `adds`, which its production builds anyway. A mech army fighting
Mutalisks takes Thors and Vikings, not Marines.

SURVIVE. While Strategy says the base is falling, any type the Body fights
with (`survival_types`) that can be trained now and hits the strongest
incident's attackers goes first, ordered by the share of the answer to that
incident it makes up, beyond the style. Only those: the model prices a
Liberator by its sieged weapon, which the Body never sieges (6 Liberators
of a bio army in `bench/comp-eficacia/004`).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from ares.dicts.unit_data import UNIT_DATA
from ares.dicts.unit_tech_requirement import UNIT_TECH_REQUIREMENT
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.ids.unit_typeid import UnitTypeId

from bot.attention import TERRAN_PRODUCTION, AttentionState
from bot.awareness import Contact, EnemyArmyBelief, ThreatIncident
from bot.ego.strategy import StrategicIntent

from ..contracts import CompositionPlan, EnemyShare, SurvivalComposition
from ..knowledge.combat import CombatModel, canonical_unit, default_model
from ..knowledge.styles import ArmyStyle

TECHLAB_OF = {
    UnitTypeId.BARRACKS: UnitTypeId.BARRACKSTECHLAB,
    UnitTypeId.FACTORY: UnitTypeId.FACTORYTECHLAB,
    UnitTypeId.STARPORT: UnitTypeId.STARPORTTECHLAB,
}

# Seconds each structure a unit's tech needs takes to build.
TECH_SECONDS = {
    UnitTypeId.BARRACKS: 46.0,
    UnitTypeId.FACTORY: 43.0,
    UnitTypeId.STARPORT: 36.0,
    UnitTypeId.ARMORY: 46.0,
    UnitTypeId.FUSIONCORE: 46.0,
    UnitTypeId.GHOSTACADEMY: 29.0,
    UnitTypeId.BARRACKSTECHLAB: 18.0,
    UnitTypeId.FACTORYTECHLAB: 18.0,
    UnitTypeId.STARPORTTECHLAB: 18.0,
}
# A structure missing from TECH_SECONDS.
_UNKNOWN_TECH_SECONDS = 45.0
# Below this share of the answer to an enemy type, a unit is not named as one.
_ANSWER_SHARE = 0.01


@dataclass(frozen=True, slots=True)
class CompositionConfig:
    # Enemy power seen, in Marines, that weighs as much as the style's doctrine.
    doctrine_power: float = 20.0
    # Weight, in Marines, of the race's prior over what the enemy army is made of.
    prior_power: float = 10.0
    # The army planned against is the observer's mean plus this many sigmas,
    # as the Assessment's.
    sigma_margin: float = 0.5
    # Seconds of tech still to build that cut a unit's worth by 1/e.
    tech_horizon: float = 60.0
    # The least share of the army a unit type enters the composition with.
    min_share: float = 0.05
    # The types SURVIVE may train beyond the style: the ones the Body fights with.
    survival_types: tuple[UnitTypeId, ...] = (
        UnitTypeId.MARINE,
        UnitTypeId.MARAUDER,
        UnitTypeId.HELLION,
        UnitTypeId.SIEGETANK,
        UnitTypeId.CYCLONE,
        UnitTypeId.THOR,
        UnitTypeId.VIKINGFIGHTER,
    )
    iterations: int = 500
    # The largest change of a resource share at which the mix is solved.
    tolerance: float = 1e-6
    # Included in the run fingerprint so a changed combat model is a new bot.
    model_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("doctrine_power", "prior_power", "tech_horizon", "tolerance"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if self.sigma_margin < 0.0:
            raise ValueError("sigma_margin must not be negative")
        if not 0.0 <= self.min_share < 1.0:
            raise ValueError("min_share must lie in [0, 1)")
        if self.iterations < 1:
            raise ValueError("iterations must be positive")
        if not self.model_digest:
            raise ValueError("model_digest must not be empty")


class CompositionPolicy:
    def __init__(
        self,
        style: ArmyStyle,
        model: CombatModel | None = None,
        config: CompositionConfig | None = None,
    ) -> None:
        self.style = style
        self.model = model or default_model()
        self.config = config or CompositionConfig(model_digest=self.model.digest)
        if self.config.model_digest != self.model.digest:
            raise ValueError("CompositionConfig model_digest does not match the combat model")
        self._validate_style()
        style_types = [unit_type for unit_type, _, _ in style.composition]
        self._support = tuple(
            unit_type for unit_type in style_types if not self._stats(unit_type).weapons
        )
        self._combat = tuple(
            dict.fromkeys(
                [unit_type for unit_type in style_types if unit_type not in self._support]
                + [unit_type for unit_type in style.adds if self._stats(unit_type).weapons]
            )
        )
        # What SURVIVE may train.
        self._trainable = tuple(
            dict.fromkeys(
                unit_type
                for unit_type in (*self._combat, *self.config.survival_types)
                if self._stats(unit_type).weapons
                and UNIT_TRAINED_FROM.get(unit_type, set()) & TERRAN_PRODUCTION
            )
        )
        resources = {
            unit_type: share * _cost(unit_type) for unit_type, share, _ in style.composition
        }
        total = sum(resources.values())
        self._support_resources = sum(resources[unit_type] for unit_type in self._support) / total
        combat_total = total * (1.0 - self._support_resources)
        self._doctrine = np.array(
            [resources.get(unit_type, 0.0) / combat_total for unit_type in self._combat]
        )
        self._baseline_resources = {
            unit_type: resource / total for unit_type, resource in resources.items()
        }
        self._dps: dict[tuple[UnitTypeId, UnitTypeId], float] = {}

    def plan(
        self,
        attention: AttentionState,
        intent: StrategicIntent,
        enemy: Iterable[tuple[UnitTypeId, float]] = (),
        *,
        produced: Iterable[tuple[UnitTypeId, float]] = (),
        army: EnemyArmyBelief | None = None,
        contacts: Iterable[Contact] = (),
        incidents: Iterable[ThreatIncident] = (),
    ) -> CompositionPlan:
        """`enemy` is the army seen alive by type, `produced` what the enemy
        was seen to build by type (`enemy` when not given), `army` the
        observer's belief."""

        config = self.config
        enemy = tuple(enemy)
        seen, unmodeled = self._by_type(enemy)
        made, unknown = self._by_type(tuple(produced) or enemy)
        for type_id, power in unknown.items():
            unmodeled[type_id] = max(unmodeled.get(type_id, 0.0), power)
        # What is alive was built.
        for type_id, power in seen.items():
            made[type_id] = max(made.get(type_id, 0.0), power)
        seen_power = sum(seen.values())
        evidence = sum(made.values())
        believed = seen_power
        if army is not None:
            believed = max(seen_power, army.power + config.sigma_margin * army.sigma)
        shares = self._belief(seen, made, believed, attention)
        availability = {
            unit_type: math.exp(-self._delay(unit_type, attention) / config.tech_horizon)
            for unit_type in self._combat
        }

        answers: dict[UnitTypeId, tuple[tuple[UnitTypeId, float], ...]] = {}
        if evidence > 0.0:
            x, answers = self._optimize(shares, evidence, availability)
        else:
            x = self._doctrine
        resources = {
            unit_type: float(share) * (1.0 - self._support_resources)
            for unit_type, share in zip(self._combat, x, strict=True)
        }
        for unit_type in self._support:
            resources[unit_type] = self._baseline_resources[unit_type]
        mix = tuple(
            (unit_type, share, availability.get(unit_type, 1.0))
            for unit_type, share in resources.items()
            if share > 0.0
        )
        if evidence > 0.0:
            units = self._units(resources)
            reason = "efficacy"
        else:
            # Exactly the style, not the style through float noise.
            units = self.style.composition
            reason = "style_baseline"

        survival = None
        if intent.emergency:
            incident = _strongest(tuple(incidents))
            if incident is not None:
                units, survival = self._survival_units(attention, units, incident, tuple(contacts))
                reason = "survival_fallback"

        return CompositionPlan(
            style=self.style.name,
            baseline=self.style.composition,
            enemy=tuple(
                EnemyShare(
                    type_id,
                    seen.get(type_id, 0.0),
                    share,
                    answers.get(type_id, ()),
                    made.get(type_id, 0.0),
                )
                for type_id, share in sorted(
                    shares.items(), key=lambda item: (-item[1], item[0].name)
                )
            ),
            seen_power=seen_power,
            believed_power=believed,
            doctrine=config.doctrine_power / (evidence + config.doctrine_power),
            produced_power=evidence,
            mix=mix,
            unmodeled=tuple(sorted(unmodeled.items(), key=lambda item: item[0].name)),
            survival=survival,
            units=units,
            tech_ready=tuple(sorted(attention.tech_ready, key=lambda item: item.name)),
            reason=reason,
        )

    def _by_type(
        self, powers: Iterable[tuple[UnitTypeId, float]]
    ) -> tuple[dict[UnitTypeId, float], dict[UnitTypeId, float]]:
        """Power by canonical type: the types the combat model knows, and
        the ones it does not."""

        known: dict[UnitTypeId, float] = {}
        unknown: dict[UnitTypeId, float] = {}
        for type_id, power in powers:
            if power <= 0.0:
                continue
            canonical = canonical_unit(type_id)
            into = known if self.model.stats(canonical) is not None else unknown
            into[canonical] = into.get(canonical, 0.0) + power
        return known, unknown

    def _belief(
        self,
        seen: dict[UnitTypeId, float],
        made: dict[UnitTypeId, float],
        believed: float,
        attention: AttentionState,
    ) -> dict[UnitTypeId, float]:
        prior_power = self.config.prior_power
        prior = self.model.prior(attention.enemy_race)
        seen_power = sum(seen.values())
        made_power = sum(made.values())
        types = set(seen) | set(made) | set(prior)
        posterior = {
            type_id: (made.get(type_id, 0.0) + prior_power * prior.get(type_id, 0.0))
            / (made_power + prior_power)
            for type_id in types
        }
        unseen = max(0.0, believed - seen_power) + prior_power
        total = seen_power + unseen
        return {
            type_id: (seen.get(type_id, 0.0) + unseen * posterior[type_id]) / total
            for type_id in types
        }

    def _optimize(
        self,
        shares: dict[UnitTypeId, float],
        evidence: float,
        availability: dict[UnitTypeId, float],
    ) -> tuple[np.ndarray, dict[UnitTypeId, tuple[tuple[UnitTypeId, float], ...]]]:
        config = self.config
        efficacy, columns = self._efficacy(self._combat, shares, availability)
        enemy = [type_id for type_id in shares if efficacy[:, columns[type_id]].any()]
        if not enemy:
            return self._doctrine, {}
        k = efficacy[:, [columns[type_id] for type_id in enemy]]
        w = np.array([shares[type_id] for type_id in enemy])
        w = w / w.sum()
        doctrine = config.doctrine_power
        x = 0.5 * self._doctrine + 0.5 / len(self._combat)
        for _ in range(config.iterations):
            strength = x @ k
            step = (evidence * x * (k @ (w / strength)) + doctrine * self._doctrine) / (
                evidence + doctrine
            )
            step = step / step.sum()
            moved = float(np.abs(step - x).max())
            x = step
            if moved < config.tolerance:
                break
        strength = x @ k
        answers = {}
        for column, type_id in enumerate(enemy):
            part = x * k[:, column] / strength[column]
            answers[type_id] = tuple(
                (self._combat[row], float(part[row]))
                for row in np.argsort(-part, kind="stable")
                if part[row] >= _ANSWER_SHARE
            )
        return x, answers

    def _efficacy(
        self,
        ours: tuple[UnitTypeId, ...],
        shares: dict[UnitTypeId, float],
        availability: dict[UnitTypeId, float],
    ) -> tuple[np.ndarray, dict[UnitTypeId, int]]:
        """k_ie for our types (rows) against `shares`' types (columns), and
        the column of each of those."""

        columns = {type_id: column for column, type_id in enumerate(shares)}
        fire = []
        for unit_type in ours:
            fire.append(
                sum(
                    share / power * self._hit(enemy, unit_type)
                    for enemy, share in shares.items()
                    if (power := self.model.power(enemy)) > 0.0
                )
            )
        # Nothing believed in can hit it: it is worth a thousand times what the
        # least threatened unit is, not infinitely more.
        floor = 1e-3 * max(fire, default=0.0) or 1.0
        efficacy = np.zeros((len(ours), len(shares)))
        for row, unit_type in enumerate(ours):
            stats = self._stats(unit_type)
            lasts = stats.hit_points / max(fire[row], floor)
            worth = availability.get(unit_type, 1.0) / _cost(unit_type)
            for enemy, column in columns.items():
                dps = self._hit(unit_type, enemy)
                if dps > 0.0:
                    efficacy[row, column] = worth * math.sqrt(dps * lasts)
        return efficacy, columns

    def _units(
        self, resources: dict[UnitTypeId, float]
    ) -> tuple[tuple[UnitTypeId, float, int], ...]:
        counts = {
            unit_type: share / _cost(unit_type)
            for unit_type, share in resources.items()
            if share > 0.0
        }
        total = sum(counts.values())
        counts = {unit_type: count / total for unit_type, count in counts.items()}
        largest = max(counts, key=lambda unit_type: (counts[unit_type], unit_type.name))
        kept = {
            unit_type: count
            for unit_type, count in counts.items()
            if count >= self.config.min_share or unit_type == largest
        }
        total = sum(kept.values())
        priorities = {unit_type: priority for unit_type, _, priority in self.style.composition}
        fallback = max(priorities.values())
        order = [unit_type for unit_type, _, _ in self.style.composition if unit_type in kept]
        order.extend(
            sorted(
                (unit_type for unit_type in kept if unit_type not in priorities),
                key=lambda unit_type: (-kept[unit_type], unit_type.name),
            )
        )
        return tuple(
            (unit_type, kept[unit_type] / total, priorities.get(unit_type, fallback))
            for unit_type in order
        )

    def _delay(self, unit_type: UnitTypeId, attention: AttentionState) -> float:
        """Seconds of tech still to build before `unit_type` can be trained:
        a structure under construction counts half its time."""

        if unit_type in attention.tech_ready:
            return 0.0
        ready = set()
        building = set()
        for structure in attention.own_structures:
            kind = canonical_unit(structure.type_id)
            (ready if structure.is_ready else building).add(kind)
        needed = set(UNIT_TECH_REQUIREMENT.get(unit_type, ())) | set(
            UNIT_TRAINED_FROM.get(unit_type, ())
        )
        delay = 0.0
        for structure in needed:
            if structure in ready:
                continue
            seconds = TECH_SECONDS.get(structure, _UNKNOWN_TECH_SECONDS)
            delay += 0.5 * seconds if structure in building else seconds
        return delay

    def _survival_units(
        self,
        attention: AttentionState,
        normal: tuple[tuple[UnitTypeId, float, int], ...],
        incident: ThreatIncident,
        contacts: tuple[Contact, ...],
    ) -> tuple[tuple[tuple[UnitTypeId, float, int], ...], SurvivalComposition]:
        by_tag = {contact.tag: contact for contact in contacts}
        members = tuple(by_tag[tag] for tag in incident.contacts if tag in by_tag)
        attackers: dict[UnitTypeId, float] = {}
        for member in members:
            canonical = canonical_unit(member.type_id)
            if self.model.stats(canonical) is not None:
                attackers[canonical] = (
                    attackers.get(canonical, 0.0) + member.power * member.confidence
                )

        if attackers:

            def reaches_incident(candidate: UnitTypeId) -> bool:
                return any(self._hit(candidate, target) > 0.0 for target in attackers)

        else:
            wants_ground = incident.ground_power > 0.0
            wants_air = incident.air_power > 0.0

            def reaches_incident(candidate: UnitTypeId) -> bool:
                hits = [weapon.hits for weapon in self._stats(candidate).weapons]
                return (wants_ground and any(on in ("ground", "any") for on in hits)) or (
                    wants_air and any(on in ("air", "any") for on in hits)
                )

        ready_producers = {
            structure.type_id for structure in attention.own_structures if structure.is_ready
        }
        candidates = tuple(
            unit_type
            for unit_type in self._trainable
            if unit_type in attention.tech_ready
            and UNIT_TRAINED_FROM.get(unit_type, set()) & ready_producers
            and reaches_incident(unit_type)
        )

        scores = {candidate: 0.0 for candidate in candidates}
        if attackers and candidates:
            total = sum(attackers.values())
            shares = {type_id: power / total for type_id, power in attackers.items()}
            efficacy, columns = self._efficacy(candidates, shares, {})
            strength = efficacy.sum(axis=0)
            for row, candidate in enumerate(candidates):
                scores[candidate] = float(
                    sum(
                        share * efficacy[row, columns[type_id]] / strength[columns[type_id]]
                        for type_id, share in shares.items()
                        if strength[columns[type_id]] > 0.0
                    )
                )
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

    def _hit(self, attacker: UnitTypeId, target: UnitTypeId) -> float:
        key = (attacker, target)
        dps = self._dps.get(key)
        if dps is None:
            dps = self._dps[key] = self.model.dps(attacker, target)
        return dps

    def _stats(self, unit_type: UnitTypeId):
        stats = self.model.stats(unit_type)
        if stats is None:
            raise ValueError(f"{unit_type.name} has no stats in the combat model")
        return stats

    def _validate_style(self) -> None:
        total = sum(share for _, share, _ in self.style.composition)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"style {self.style.name} composition must sum to 1")
        for unit_type, share, priority in self.style.composition:
            self._stats(unit_type)
            if share <= 0.0:
                raise ValueError(f"style unit {unit_type.name} has a non-positive share")
            if not 0 <= priority <= 10:
                raise ValueError(f"style unit {unit_type.name} has invalid priority")
        if all(not self._stats(unit_type).weapons for unit_type, _, _ in self.style.composition):
            raise ValueError(f"style {self.style.name} has no unit that fights")
        for unit_type in self.style.adds:
            self._stats(unit_type)


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


def _cost(unit_type: UnitTypeId) -> float:
    data = UNIT_DATA[unit_type]
    return float(data["minerals"]) + float(data["gas"])


def _strongest(incidents: tuple[ThreatIncident, ...]) -> ThreatIncident | None:
    return max(
        incidents,
        key=lambda incident: (incident.threat, incident.power, incident.incident_id),
        default=None,
    )


__all__ = [
    "CompositionConfig",
    "CompositionPolicy",
    "reactor_share",
]

"""The combat model: how hard one unit type hits another, and how much it takes.

`dps(a, b)` is the damage a unit of type `a` deals per second to one of type
`b`: the best of `a`'s weapons that reaches `b`'s layer, each attack's damage
plus its bonus against `b`'s attributes, less `b`'s armor (never below the
game's floor of half a point), a shot never more than `b`'s hit points (a
Thor's 60 kill one Zergling), times the targets one shot covers. Armor
guards only the hull: against a Protoss unit it is weighed by the share of
its hit points that are not shields.

`power(e)` is the Lanchester fighting value `sqrt(dps * hit points)` against
an unarmored target, in Marines -- `bot.attention.units.unit_power` from the
table instead of a unit in the game. It converts the enemy's power, which is
what Awareness remembers, into units.

The table (`combat.yml`) is the fallback. `with_client` reads the running
client's type data, which says what the patch really is: on the AI Arena
client (4.10) a Cyclone is not the one of 5.0.14.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sc2.data import Attribute, Race
from sc2.dicts.unit_unit_alias import UNIT_UNIT_ALIAS
from sc2.ids.unit_typeid import UnitTypeId

from bot.attention import MARINE_POWER

# The game's floor for the damage of one attack after armor.
MIN_DAMAGE = 0.5
TARGETS = ("ground", "air", "any")
# The client's Weapon.TargetType.
_CLIENT_TARGETS = {1: "ground", 2: "air", 3: "any"}
_RACES = (Race.Terran, Race.Protoss, Race.Zerg)


def canonical_unit(type_id: UnitTypeId) -> UnitTypeId:
    return UNIT_UNIT_ALIAS.get(type_id, type_id)


@dataclass(frozen=True, slots=True)
class Weapon:
    hits: str
    damage: float
    cooldown: float
    attacks: int = 1
    bonus: tuple[tuple[Attribute, float], ...] = ()
    splash: float = 1.0

    def reaches(self, ground: bool, air: bool) -> bool:
        return (ground and self.hits in ("ground", "any")) or (air and self.hits in ("air", "any"))


@dataclass(frozen=True, slots=True)
class UnitStats:
    type_id: UnitTypeId
    hp: float
    armor: float
    attributes: frozenset[Attribute]
    weapons: tuple[Weapon, ...]
    shields: float = 0.0
    flying: bool = False
    # Walks on the ground and is hit by anti-air too: the Colossus.
    both_layers: bool = False
    # The client types its weapons are read from; empty keeps the table's.
    client: tuple[UnitTypeId, ...] = ()

    @property
    def hit_points(self) -> float:
        return self.hp + self.shields

    @property
    def layers(self) -> tuple[bool, bool]:
        """Whether it can be hit as a ground unit, and as an air unit."""

        if self.both_layers:
            return True, True
        return not self.flying, self.flying


@dataclass(frozen=True, slots=True)
class CombatModel:
    units: Mapping[UnitTypeId, UnitStats]
    # Share of the enemy army's power by type, per race, before any is seen.
    priors: Mapping[Race, Mapping[UnitTypeId, float]]
    digest: str

    @classmethod
    def load(cls, path: Path | None = None) -> CombatModel:
        path = path or Path(__file__).with_name("combat.yml")
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ValueError(f"cannot load combat model {path}: {error}") from error
        if not isinstance(raw, dict) or set(raw) != {"units", "priors"}:
            raise ValueError(f"combat model {path} must hold exactly `units` and `priors`")
        units = {
            stats.type_id: stats
            for stats in (_unit(name, entry) for name, entry in raw["units"].items())
        }
        priors: dict[Race, dict[UnitTypeId, float]] = {}
        for race_name, shares in raw["priors"].items():
            race = _race(race_name)
            prior = {_type(name): float(share) for name, share in shares.items()}
            unknown = sorted(type_id.name for type_id in prior if type_id not in units)
            if unknown:
                raise ValueError(f"prior of {race_name} names units with no stats: {unknown}")
            if min(prior.values(), default=0.0) <= 0.0 or abs(sum(prior.values()) - 1.0) > 1e-9:
                raise ValueError(f"prior of {race_name} must be positive shares summing to 1")
            priors[race] = prior
        if set(priors) != set(_RACES):
            raise ValueError("the combat model needs a prior for each of the three races")
        return cls._build(units, priors)

    @classmethod
    def _build(
        cls,
        units: Mapping[UnitTypeId, UnitStats],
        priors: Mapping[Race, Mapping[UnitTypeId, float]],
    ) -> CombatModel:
        semantic = {
            "units": [_describe(units[type_id]) for type_id in sorted(units, key=_name)],
            "priors": [
                (race.name, sorted((type_id.name, share) for type_id, share in prior.items()))
                for race, prior in sorted(priors.items(), key=lambda item: item[0].name)
            ],
        }
        encoded = json.dumps(semantic, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
        return cls(dict(units), {race: dict(prior) for race, prior in priors.items()}, digest)

    def with_client(self, game_data: Any) -> tuple[CombatModel, tuple[str, ...]]:
        """This model with armor, attributes and weapons as the client's type
        data says, and what changed beyond rounding. Cooldowns are rescaled
        so that the client's Marine shoots as the table's: the table's seconds
        are the unit everything else here is in. Splash is the table's: the
        client does not say it."""

        scale = _cooldown_scale(self.units.get(UnitTypeId.MARINE), game_data)
        units = dict(self.units)
        changes: list[str] = []
        for type_id, stats in self.units.items():
            if not stats.client:
                continue
            protos = [_proto(game_data, client) for client in stats.client]
            if any(proto is None for proto in protos):
                continue
            weapons = _ordered(
                _client_weapon(weapon, stats.weapons, scale)
                for proto in protos
                for weapon in proto.weapons
            )
            if stats.weapons and not weapons:
                continue
            refreshed = replace(
                stats,
                armor=float(protos[0].armor),
                attributes=frozenset(Attribute(value) for value in protos[0].attributes),
                weapons=weapons,
            )
            units[type_id] = refreshed
            changes.extend(_differences(stats, refreshed))
        return CombatModel._build(units, self.priors), tuple(changes)

    def stats(self, type_id: UnitTypeId) -> UnitStats | None:
        return self.units.get(canonical_unit(type_id))

    def dps(self, attacker: UnitTypeId, target: UnitTypeId) -> float:
        hitting, hit = self.stats(attacker), self.stats(target)
        if hitting is None or hit is None:
            return 0.0
        ground, air = hit.layers
        total = hit.hit_points
        armor = hit.armor * hit.hp / total if total > 0.0 else hit.armor
        best = 0.0
        for weapon in hitting.weapons:
            if not weapon.reaches(ground, air):
                continue
            damage = weapon.damage + sum(
                bonus for attribute, bonus in weapon.bonus if attribute in hit.attributes
            )
            # A shot kills no more than one target's hit points.
            shot = min(weapon.attacks * max(MIN_DAMAGE, damage - armor), total)
            best = max(best, shot / weapon.cooldown * weapon.splash)
        return best

    def power(self, type_id: UnitTypeId) -> float:
        stats = self.stats(type_id)
        if stats is None or not stats.weapons:
            return 0.0
        damage = max(
            weapon.attacks * weapon.damage / weapon.cooldown * weapon.splash
            for weapon in stats.weapons
        )
        return math.sqrt(damage * stats.hit_points) / MARINE_POWER

    def prior(self, race: Race) -> dict[UnitTypeId, float]:
        """The race's prior; the three races' mean while the race is unknown."""

        if race in self.priors:
            return dict(self.priors[race])
        mean: dict[UnitTypeId, float] = {}
        for known in _RACES:
            for type_id, share in self.priors[known].items():
                mean[type_id] = mean.get(type_id, 0.0) + share / len(_RACES)
        return mean


@lru_cache(maxsize=1)
def default_model() -> CombatModel:
    return CombatModel.load()


def _unit(name: Any, entry: Any) -> UnitStats:
    type_id = _type(name)
    if type_id in UNIT_UNIT_ALIAS:
        raise ValueError(f"{name} is a mode; use {UNIT_UNIT_ALIAS[type_id].name}")
    if not isinstance(entry, dict):
        raise ValueError(f"stats of {name} must be a mapping")
    known = {"hp", "shields", "armor", "attributes", "flying", "both_layers", "weapons", "client"}
    if set(entry) - known:
        raise ValueError(f"stats of {name} have unknown keys {sorted(set(entry) - known)}")
    hp = float(entry["hp"])
    if hp <= 0.0 or float(entry.get("shields", 0.0)) < 0.0:
        raise ValueError(f"{name} needs positive hp and non-negative shields")
    client = entry.get("client", [name])
    return UnitStats(
        type_id=type_id,
        hp=hp,
        shields=float(entry.get("shields", 0.0)),
        armor=float(entry["armor"]),
        attributes=frozenset(_attribute(item, name) for item in entry["attributes"]),
        weapons=_ordered(_weapon(item, name) for item in entry["weapons"]),
        flying=bool(entry.get("flying", False)),
        both_layers=bool(entry.get("both_layers", False)),
        client=tuple(_type(item) for item in client),
    )


def _weapon(entry: Any, owner: str) -> Weapon:
    if not isinstance(entry, dict):
        raise ValueError(f"a weapon of {owner} must be a mapping")
    known = {"hits", "damage", "cooldown", "attacks", "bonus", "splash"}
    if set(entry) - known:
        raise ValueError(f"a weapon of {owner} has unknown keys {sorted(set(entry) - known)}")
    weapon = Weapon(
        hits=str(entry["hits"]),
        damage=float(entry["damage"]),
        cooldown=float(entry["cooldown"]),
        attacks=int(entry.get("attacks", 1)),
        bonus=tuple(
            sorted(
                (
                    (_attribute(name, owner), float(bonus))
                    for name, bonus in entry.get("bonus", {}).items()
                ),
                key=lambda item: item[0].value,
            )
        ),
        splash=float(entry.get("splash", 1.0)),
    )
    if weapon.hits not in TARGETS:
        raise ValueError(f"a weapon of {owner} targets {weapon.hits!r}; known: {TARGETS}")
    if weapon.damage < 0.0 or weapon.cooldown <= 0.0 or weapon.attacks < 1 or weapon.splash < 1.0:
        raise ValueError(
            f"a weapon of {owner} has an impossible damage, cooldown, attacks or splash"
        )
    return weapon


def _client_weapon(proto: Any, table: tuple[Weapon, ...], scale: float) -> Weapon:
    on = _CLIENT_TARGETS.get(int(proto.type), "any")
    splash = max(
        (weapon.splash for weapon in table if "any" in (on, weapon.hits) or on == weapon.hits),
        default=1.0,
    )
    return Weapon(
        hits=on,
        damage=float(proto.damage),
        cooldown=float(proto.speed) * scale,
        attacks=int(proto.attacks),
        bonus=tuple(
            sorted(
                ((Attribute(item.attribute), float(item.bonus)) for item in proto.damage_bonus),
                key=lambda item: item[0].value,
            )
        ),
        splash=splash,
    )


def _ordered(weapons: Iterable[Weapon]) -> tuple[Weapon, ...]:
    """Ground before air before any: the order a type's weapons are listed
    in says nothing."""

    return tuple(sorted(weapons, key=lambda weapon: (TARGETS.index(weapon.hits), weapon.damage)))


def _differences(before: UnitStats, after: UnitStats) -> list[str]:
    """Each field the client changed, a cooldown only beyond 2 % (the
    rescaling's rounding)."""

    name = before.type_id.name
    changed = []
    if before.armor != after.armor:
        changed.append(f"{name}.armor: {before.armor:g} -> {after.armor:g}")
    if before.attributes != after.attributes:
        old = sorted(attribute.name for attribute in before.attributes)
        new = sorted(attribute.name for attribute in after.attributes)
        changed.append(f"{name}.attributes: {old} -> {new}")
    if len(before.weapons) != len(after.weapons):
        old = [weapon.hits for weapon in before.weapons]
        new = [weapon.hits for weapon in after.weapons]
        return [*changed, f"{name}.weapons: {old} -> {new}"]
    for old, new in zip(before.weapons, after.weapons, strict=True):
        field = f"{name}.{old.hits}"
        for attribute in ("hits", "damage", "attacks"):
            if getattr(old, attribute) != getattr(new, attribute):
                changed.append(
                    f"{field}.{attribute}: {getattr(old, attribute)} -> {getattr(new, attribute)}"
                )
        if old.bonus != new.bonus:
            changed.append(
                f"{field}.bonus: {[(a.name, b) for a, b in old.bonus]} -> "
                f"{[(a.name, b) for a, b in new.bonus]}"
            )
        if abs(new.cooldown - old.cooldown) > 0.02 * old.cooldown:
            changed.append(f"{field}.cooldown: {old.cooldown:g} -> {new.cooldown:.3g}")
    return changed


def _cooldown_scale(marine: UnitStats | None, game_data: Any) -> float:
    proto = _proto(game_data, UnitTypeId.MARINE)
    if marine is None or not marine.weapons or proto is None or not proto.weapons:
        return 1.0
    client = float(proto.weapons[0].speed)
    return marine.weapons[0].cooldown / client if client > 0.0 else 1.0


def _proto(game_data: Any, type_id: UnitTypeId) -> Any | None:
    try:
        return game_data.units[type_id.value]._proto
    except (AttributeError, KeyError, TypeError):
        return None


def _describe(stats: UnitStats) -> dict[str, Any]:
    return {
        "type": stats.type_id.name,
        "hp": stats.hp,
        "shields": stats.shields,
        "armor": stats.armor,
        "attributes": sorted(attribute.name for attribute in stats.attributes),
        "flying": stats.flying,
        "both_layers": stats.both_layers,
        "weapons": [
            {
                "hits": weapon.hits,
                "damage": weapon.damage,
                "attacks": weapon.attacks,
                "cooldown": round(weapon.cooldown, 3),
                "bonus": [(attribute.name, bonus) for attribute, bonus in weapon.bonus],
                "splash": weapon.splash,
            }
            for weapon in stats.weapons
        ],
    }


def _type(name: Any) -> UnitTypeId:
    if not isinstance(name, str):
        raise ValueError(f"unit name {name!r} must be a string")
    try:
        return UnitTypeId[name]
    except KeyError as error:
        raise ValueError(f"unknown UnitTypeId {name!r}") from error


def _attribute(name: Any, owner: str) -> Attribute:
    try:
        return Attribute[str(name)]
    except KeyError as error:
        raise ValueError(f"unknown attribute {name!r} of {owner}") from error


def _race(name: Any) -> Race:
    try:
        return Race[str(name)]
    except KeyError as error:
        raise ValueError(f"unknown race {name!r}") from error


def _name(type_id: UnitTypeId) -> str:
    return type_id.name

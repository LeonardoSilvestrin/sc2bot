"""Validated, ordered Terran responses to canonical enemy unit types."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_unit_alias import UNIT_UNIT_ALIAS
from sc2.ids.unit_typeid import UnitTypeId

from bot.attention import TERRAN_PRODUCTION

# What every unit the composition policy may ask Ares to train can hit:
# (ground targets, air targets).
REACH: dict[UnitTypeId, tuple[bool, bool]] = {
    UnitTypeId.MARINE: (True, True),
    UnitTypeId.MARAUDER: (True, False),
    UnitTypeId.SIEGETANK: (True, False),
    UnitTypeId.HELLION: (True, False),
    UnitTypeId.CYCLONE: (True, True),
    UnitTypeId.THOR: (True, True),
    UnitTypeId.WIDOWMINE: (True, True),
    UnitTypeId.VIKINGFIGHTER: (False, True),
    UnitTypeId.MEDIVAC: (False, False),
}

# Colossi walk on the ground but can also be targeted by anti-air weapons.
_BOTH_LAYER_TARGETS = frozenset({UnitTypeId.COLOSSUS})
_GROUND_MODES = frozenset({UnitTypeId.VIKINGASSAULT})
_AIR_TARGETS = frozenset(
    {
        UnitTypeId.BANSHEE,
        UnitTypeId.BATTLECRUISER,
        UnitTypeId.BROODLORD,
        UnitTypeId.CARRIER,
        UnitTypeId.CORRUPTOR,
        UnitTypeId.LIBERATOR,
        UnitTypeId.LIBERATORAG,
        UnitTypeId.LOCUSTMPFLYING,
        UnitTypeId.MEDIVAC,
        UnitTypeId.MOTHERSHIP,
        UnitTypeId.MUTALISK,
        UnitTypeId.OBSERVER,
        UnitTypeId.OBSERVERSIEGEMODE,
        UnitTypeId.ORACLE,
        UnitTypeId.OVERLORD,
        UnitTypeId.OVERSEER,
        UnitTypeId.PHOENIX,
        UnitTypeId.RAVEN,
        UnitTypeId.TEMPEST,
        UnitTypeId.VIKINGFIGHTER,
        UnitTypeId.VIPER,
        UnitTypeId.VOIDRAY,
        UnitTypeId.WARPPRISM,
        UnitTypeId.WARPPRISMPHASING,
    }
)


def canonical_unit(type_id: UnitTypeId) -> UnitTypeId:
    return UNIT_UNIT_ALIAS.get(type_id, type_id)


def target_layers(type_id: UnitTypeId) -> tuple[bool, bool]:
    """Whether the observed enemy type can be hit as ground and air."""

    canonical = canonical_unit(type_id)
    if canonical in _BOTH_LAYER_TARGETS:
        return True, True
    # The mode, not only its canonical alias, determines physical flight.
    # UNIT_DATA currently marks Carrier as non-flying, so the known air set is
    # authoritative and the data remains a fallback for unlisted types.
    if type_id in _GROUND_MODES:
        return True, False
    from ares.dicts.unit_data import UNIT_DATA

    flying = type_id in _AIR_TARGETS or bool(UNIT_DATA.get(type_id, {}).get("flying", False))
    return (not flying, flying)


def can_reach(response: UnitTypeId, enemy: UnitTypeId) -> bool:
    ground, air = REACH[response]
    target_ground, target_air = target_layers(enemy)
    return (ground and target_ground) or (air and target_air)


def physics_digest() -> str:
    """Fingerprint the targeting facts that affect counter selection."""

    semantic = {
        "reach": [
            (unit_type.name, ground, air)
            for unit_type, (ground, air) in sorted(REACH.items(), key=lambda item: item[0].name)
        ],
        "air": sorted(unit_type.name for unit_type in _AIR_TARGETS),
        "both": sorted(unit_type.name for unit_type in _BOTH_LAYER_TARGETS),
        "ground_modes": sorted(unit_type.name for unit_type in _GROUND_MODES),
    }
    encoded = json.dumps(semantic, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate counter key {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


@dataclass(frozen=True, slots=True)
class CounterCatalog:
    """Immutable catalog. ``None`` means absent; ``()`` means known-empty."""

    entries: tuple[tuple[UnitTypeId, tuple[UnitTypeId, ...]], ...]
    digest: str

    @classmethod
    def load(cls, directory: Path | None = None) -> CounterCatalog:
        root = directory or Path(__file__).with_name("counters")
        parsed: dict[UnitTypeId, tuple[UnitTypeId, ...]] = {}
        semantic: list[tuple[str, list[tuple[str, list[str]]]]] = []
        for filename in ("terran.yml", "protoss.yml", "zerg.yml"):
            path = root / filename
            try:
                raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
            except (OSError, yaml.YAMLError) as error:
                raise ValueError(f"cannot load counter catalog {path}: {error}") from error
            if not isinstance(raw, dict):
                raise ValueError(f"counter catalog {path} must be a mapping")
            file_entries: list[tuple[str, list[str]]] = []
            for enemy_name, response_names in raw.items():
                if not isinstance(enemy_name, str):
                    raise ValueError(f"counter key in {path} must be a UnitTypeId name")
                enemy = _unit_type(enemy_name, path)
                if enemy in UNIT_UNIT_ALIAS:
                    raise ValueError(
                        f"counter key {enemy_name} in {path} is not canonical; "
                        f"use {UNIT_UNIT_ALIAS[enemy].name}"
                    )
                if enemy in parsed:
                    raise ValueError(f"counter key {enemy_name} occurs in more than one file")
                if not isinstance(response_names, list):
                    raise ValueError(f"responses for {enemy_name} in {path} must be a list")
                responses = tuple(_unit_type(name, path) for name in response_names)
                if len(set(responses)) != len(responses):
                    raise ValueError(f"responses for {enemy_name} in {path} contain a duplicate")
                for response in responses:
                    producers = UNIT_TRAINED_FROM.get(response, set())
                    if not producers & TERRAN_PRODUCTION:
                        raise ValueError(
                            f"counter {response.name} for {enemy_name} is not trained by "
                            "Terran army production"
                        )
                    if response in UNIT_UNIT_ALIAS:
                        raise ValueError(f"counter response {response.name} is not canonical")
                    if response not in REACH:
                        raise ValueError(f"counter response {response.name} has no REACH entry")
                    if not can_reach(response, enemy):
                        raise ValueError(
                            f"counter {response.name} cannot hit catalog target {enemy_name}"
                        )
                parsed[enemy] = responses
                file_entries.append((enemy.name, [response.name for response in responses]))
            semantic.append((filename, sorted(file_entries)))
        encoded = json.dumps(semantic, separators=(",", ":"), ensure_ascii=True)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
        return cls(tuple(sorted(parsed.items(), key=lambda item: item[0].name)), digest)

    @property
    def response_types(self) -> frozenset[UnitTypeId]:
        return frozenset(response for _, responses in self.entries for response in responses)

    def counters_for(self, type_id: UnitTypeId) -> tuple[UnitTypeId, ...] | None:
        canonical = canonical_unit(type_id)
        return dict(self.entries).get(canonical)


def _unit_type(name: Any, path: Path) -> UnitTypeId:
    if not isinstance(name, str):
        raise ValueError(f"unit name {name!r} in {path} must be a string")
    try:
        return UnitTypeId[name]
    except KeyError as error:
        raise ValueError(f"unknown UnitTypeId {name!r} in {path}") from error

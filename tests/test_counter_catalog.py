from __future__ import annotations

from pathlib import Path

import pytest
from sc2.ids.unit_typeid import UnitTypeId

from bot.ego.planners.economy.knowledge.counter_catalog import (
    CounterCatalog,
    canonical_unit,
    target_layers,
)


def write_catalog(root: Path, *, terran: str = "MARINE: [SIEGETANK]\n") -> None:
    (root / "terran.yml").write_text(terran, encoding="utf-8")
    (root / "protoss.yml").write_text("COLOSSUS: [VIKINGFIGHTER]\n", encoding="utf-8")
    (root / "zerg.yml").write_text("BROODLING: []\n", encoding="utf-8")


def test_the_default_catalog_loads_and_empty_differs_from_absent() -> None:
    catalog = CounterCatalog.load()

    assert catalog.counters_for(UnitTypeId.MUTALISK) == (
        UnitTypeId.THOR,
        UnitTypeId.MARINE,
        UnitTypeId.CYCLONE,
        UnitTypeId.VIKINGFIGHTER,
    )
    assert catalog.counters_for(UnitTypeId.BROODLING) == ()
    assert catalog.counters_for(UnitTypeId.CHANGELING) is None


def test_aliases_lookup_the_canonical_entry_and_colossus_has_both_layers() -> None:
    catalog = CounterCatalog.load()

    assert canonical_unit(UnitTypeId.SIEGETANKSIEGED) is UnitTypeId.SIEGETANK
    assert catalog.counters_for(UnitTypeId.SIEGETANKSIEGED) == catalog.counters_for(
        UnitTypeId.SIEGETANK
    )
    assert target_layers(UnitTypeId.COLOSSUS) == (True, True)


def test_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    write_catalog(tmp_path, terran="MARINE: [SIEGETANK]\nMARINE: [HELLION]\n")

    with pytest.raises(ValueError, match="duplicate counter key"):
        CounterCatalog.load(tmp_path)


def test_alias_keys_and_non_terran_responses_are_rejected(tmp_path: Path) -> None:
    write_catalog(tmp_path, terran="SIEGETANKSIEGED: [SIEGETANK]\n")
    with pytest.raises(ValueError, match="not canonical"):
        CounterCatalog.load(tmp_path)

    write_catalog(tmp_path, terran="MARINE: [ZEALOT]\n")
    with pytest.raises(ValueError, match="not trained by Terran"):
        CounterCatalog.load(tmp_path)


def test_catalog_content_changes_its_digest(tmp_path: Path) -> None:
    write_catalog(tmp_path)
    first = CounterCatalog.load(tmp_path).digest
    write_catalog(tmp_path, terran="MARINE: [HELLION, SIEGETANK]\n")

    assert CounterCatalog.load(tmp_path).digest != first

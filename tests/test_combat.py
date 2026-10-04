from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId

from bot.ego.planners.economy.knowledge.combat import CombatModel, default_model


def test_the_table_loads_and_its_digest_is_stable() -> None:
    model = default_model()

    assert CombatModel.load().digest == model.digest
    for race in (Race.Terran, Race.Protoss, Race.Zerg):
        assert sum(model.prior(race).values()) == pytest.approx(1.0)
    assert sum(model.prior(Race.Random).values()) == pytest.approx(1.0)


def test_damage_counts_bonus_armor_and_layers() -> None:
    model = default_model()

    # (10 + 10 against Armored - 1 armor) every 1.07 s.
    assert model.dps(UnitTypeId.MARAUDER, UnitTypeId.ROACH) == pytest.approx(19.0 / 1.07)
    assert model.dps(UnitTypeId.MARAUDER, UnitTypeId.ZERGLING) == pytest.approx(10.0 / 1.07)
    assert model.dps(UnitTypeId.MARAUDER, UnitTypeId.MUTALISK) == 0.0
    assert model.dps(UnitTypeId.VIKINGFIGHTER, UnitTypeId.ZERGLING) == 0.0
    # A Colossus is hit from the air as well.
    assert model.dps(UnitTypeId.VIKINGFIGHTER, UnitTypeId.COLOSSUS) > 0.0
    # Modes are their unit.
    assert model.dps(UnitTypeId.MARINE, UnitTypeId.SIEGETANKSIEGED) == model.dps(
        UnitTypeId.MARINE, UnitTypeId.SIEGETANK
    )


def test_shields_dilute_armor_and_a_shot_kills_one_target_at_most() -> None:
    model = default_model()

    # A Zealot's armor guards its 100 hull of 150 hit points.
    assert model.dps(UnitTypeId.MARINE, UnitTypeId.ZEALOT) == pytest.approx(
        (6.0 - 100.0 / 150.0) / 0.61
    )
    # A Thor's 2 x 30 kill one Zergling of 35.
    assert model.dps(UnitTypeId.THOR, UnitTypeId.ZERGLING) == pytest.approx(35.0 / 0.91)
    # Splash multiplies what one shot does, capped at a Zergling each.
    assert model.dps(UnitTypeId.SIEGETANK, UnitTypeId.MARINE) == pytest.approx(40.0 / 2.14 * 2.5)
    assert model.dps(UnitTypeId.SIEGETANK, UnitTypeId.ZERGLING) == pytest.approx(35.0 / 2.14 * 2.5)


def test_power_is_counted_in_marines() -> None:
    model = default_model()

    assert model.power(UnitTypeId.MARINE) == pytest.approx(1.0, rel=1e-2)
    assert model.power(UnitTypeId.MEDIVAC) == 0.0
    assert model.power(UnitTypeId.THOR) > model.power(UnitTypeId.MARINE)


def _proto(weapons=(), armor=0.0, attributes=(1, 3)):
    return SimpleNamespace(
        _proto=SimpleNamespace(weapons=list(weapons), armor=armor, attributes=list(attributes))
    )


def _weapon(target: int, damage: float, speed: float, attacks: int = 1, bonus=()):
    return SimpleNamespace(
        type=target,
        damage=damage,
        speed=speed,
        attacks=attacks,
        damage_bonus=[SimpleNamespace(attribute=a, bonus=b) for a, b in bonus],
    )


def test_the_client_wins_and_its_seconds_are_rescaled_to_the_table() -> None:
    model = default_model()
    # A client that counts in Normal seconds: the Marine shoots every 0.61 * 1.4.
    units = {
        UnitTypeId.MARINE.value: _proto([_weapon(3, 6.0, 0.61 * 1.4)]),
        UnitTypeId.CYCLONE.value: _proto(
            [_weapon(3, 11.0, 0.71 * 1.4)], armor=1.0, attributes=(2, 4)
        ),
        # Listed air first: the order of a type's weapons says nothing.
        UnitTypeId.THOR.value: _proto(
            [_weapon(2, 6.0, 2.14 * 1.4, 4, ((1, 6.0),)), _weapon(1, 30.0, 0.91 * 1.4, 2)],
            armor=1.0,
            attributes=(2, 4, 7),
        ),
        UnitTypeId.BANELING.value: _proto([_weapon(1, 16.0, 0.01)]),
    }

    refreshed, changed = model.with_client(SimpleNamespace(units=units))

    assert refreshed.dps(UnitTypeId.MARINE, UnitTypeId.ZERGLING) == pytest.approx(
        model.dps(UnitTypeId.MARINE, UnitTypeId.ZERGLING)
    )
    assert refreshed.dps(UnitTypeId.CYCLONE, UnitTypeId.ZERGLING) == pytest.approx(11.0 / 0.71)
    assert changed == ("CYCLONE.any.damage: 18.0 -> 11.0",)
    # The Thor's air weapon keeps the table's splash.
    assert refreshed.dps(UnitTypeId.THOR, UnitTypeId.MUTALISK) == pytest.approx(
        model.dps(UnitTypeId.THOR, UnitTypeId.MUTALISK)
    )
    # A Baneling attacks once: the table's, whatever the client says.
    assert refreshed.stats(UnitTypeId.BANELING) == model.stats(UnitTypeId.BANELING)
    # Types the client did not answer for keep the table's.
    assert refreshed.stats(UnitTypeId.ROACH) == model.stats(UnitTypeId.ROACH)
    assert refreshed.digest != model.digest


def _write(root: Path, units: str, priors: str | None = None) -> Path:
    priors = priors or (
        "priors:\n  Terran: {MARINE: 1.0}\n  Protoss: {MARINE: 1.0}\n  Zerg: {MARINE: 1.0}\n"
    )
    path = root / "combat.yml"
    path.write_text("units:\n" + units + priors, encoding="utf-8")
    return path


MARINE = (
    "  MARINE:\n"
    "    hp: 45\n"
    "    armor: 0\n"
    "    attributes: [Light, Biological]\n"
    "    weapons:\n"
    "      - {hits: any, damage: 6, cooldown: 0.61}\n"
)


def test_a_minimal_table_loads(tmp_path) -> None:
    model = CombatModel.load(_write(tmp_path, MARINE))

    assert model.power(UnitTypeId.MARINE) == pytest.approx(1.0, rel=1e-2)


@pytest.mark.parametrize(
    ("units", "priors", "message"),
    [
        (MARINE.replace("MARINE:", "SIEGETANKSIEGED:"), None, "is a mode"),
        (MARINE.replace("hits: any", "hits: sea"), None, "targets"),
        (MARINE.replace("cooldown: 0.61", "cooldown: 0"), None, "impossible"),
        (MARINE.replace("[Light, Biological]", "[Fluffy]"), None, "unknown attribute"),
        (MARINE + "    speed: 3\n", None, "unknown keys"),
        (
            MARINE,
            "priors:\n  Terran: {MARINE: 0.5}\n  Protoss: {MARINE: 1.0}\n  Zerg: {MARINE: 1.0}\n",
            "summing to 1",
        ),
        (MARINE, "priors:\n  Terran: {MARINE: 1.0}\n", "each of the three races"),
        (
            MARINE,
            "priors:\n  Terran: {ROACH: 1.0}\n  Protoss: {MARINE: 1.0}\n  Zerg: {MARINE: 1.0}\n",
            "no stats",
        ),
    ],
)
def test_a_wrong_table_is_refused(tmp_path, units: str, priors: str | None, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        CombatModel.load(_write(tmp_path, units, priors))

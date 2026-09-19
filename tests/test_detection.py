"""Detection: a cloaked or burrowed enemy nothing detects is scanned where the
army can shoot it, the Orbitals keep a scan's energy, and every base gets a
Missile Turret.

In `bench/all4/000` a burrowed Lurker (`LURKERMPBURROWED`, `visible: true`)
sat at (64.65, 86.56) from 771 s on, in reach of the army, and nothing of the
bot could detect it.
"""

from __future__ import annotations

import pytest
from ares.behaviors.macro import BuildStructure
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import unit_view
from bot.awareness import AwarenessModel
from bot.body.behaviors import detection as detection_behavior
from bot.body.behaviors import economy as economy_behavior
from bot.ego.planners import DetectionPlan
from bot.ego.planners.intel.detection import Detection, DetectionConfig
from bot.logs import Logs
from bot.main import Layers, play_frame

from .fakes import MAIN, MAP, NATURAL, FakeBot, FakeLogger, FakeUnit, attention, unit
from .test_economy import planned

LURKER = UnitTypeId.LURKERMPBURROWED
ORBITAL = UnitTypeId.ORBITALCOMMAND


def lurker(tag=900, x=30.0, y=30.0):
    return unit(tag, LURKER, x, y, power=2.0, hidden=True)


def orbital(tag=1, energy=50.0, *, ready=True):
    return unit(tag, ORBITAL, 10.5, 10.5, power=0.0, structure=True, energy=energy, ready=ready)


ONE_ORBITAL = (orbital(),)


def marines(count=3, x=30.0, y=24.0, first=200):
    return tuple(unit(first + index, x=x, y=y) for index in range(count))


def plan(
    detection,
    *,
    time=500.0,
    enemies=(),
    own=(),
    structures=ONE_ORBITAL,
    bases=(MAIN,),
    awareness=None,
):
    frame = attention(
        time=time,
        enemy_units=enemies,
        own_units=own,
        own_structures=structures,
        bases=bases,
    )
    model = awareness or AwarenessModel()
    return detection.plan(frame, model.infer(frame))


def test_nothing_before_a_cloaked_enemy_was_seen() -> None:
    result = plan(Detection(), own=marines())

    assert result == DetectionPlan(
        scan=None,
        turrets=(),
        engineering_bay=False,
        energy_reserve=0.0,
        reason="no_cloak_seen",
        inputs=result.inputs,
    )
    assert dict(result.inputs)["cloak_seen_at"] == -1.0


def test_a_hidden_enemy_near_the_army_is_scanned_and_the_bases_get_turrets() -> None:
    ebay = unit(5, UnitTypeId.ENGINEERINGBAY, 14, 14, power=0.0, structure=True)
    # Exactly `turret_cover` from the natural.
    covering = unit(6, UnitTypeId.MISSILETURRET, 30.5, 27.5, power=0.0, structure=True)

    result = plan(
        Detection(),
        enemies=(lurker(),),
        own=marines(),
        structures=(orbital(), ebay, covering),
        bases=(MAIN, NATURAL),
    )

    assert result.scan == Point2((30.0, 30.0))
    assert result.reason == "scan_hidden_enemy"
    assert result.turrets == (MAIN.position,)
    assert not result.engineering_bay
    assert result.energy_reserve == DetectionConfig().scan_reserve
    inputs = dict(result.inputs)
    assert inputs["hidden_enemies"] == 1.0
    assert inputs["cloak_seen_at"] == 500.0
    assert inputs["army_near_hidden"] == 3.0
    assert inputs["orbitals_with_scan"] == 1.0


def test_an_unfinished_turret_covers_and_no_engineering_bay_asks_for_one() -> None:
    building = unit(6, UnitTypeId.MISSILETURRET, 12, 12, power=0.0, structure=True, ready=False)

    result = plan(Detection(), enemies=(lurker(),), structures=(orbital(), building))

    assert result.turrets == ()
    assert result.engineering_bay


def test_a_scan_is_not_repeated_while_it_lasts() -> None:
    config = DetectionConfig(scan_duration=12.5)
    detection = Detection(config)
    model = AwarenessModel()

    first = plan(detection, time=500.0, enemies=(lurker(),), own=marines(), awareness=model)
    # Another hidden enemy at the edge of the revealed area.
    during = plan(
        detection,
        time=512.4,
        enemies=(lurker(), lurker(901, 30 + config.scan_radius, 30)),
        own=(*marines(), *marines(3, x=43, first=300)),
        awareness=model,
    )
    after = plan(detection, time=512.5, enemies=(lurker(),), own=marines(), awareness=model)

    assert first.scan == Point2((30.0, 30.0))
    assert (during.scan, during.reason) == (None, "hidden_enemy_scanned")
    assert dict(during.inputs)["active_scans"] == 1.0
    assert after.scan == Point2((30.0, 30.0))


@pytest.mark.parametrize(
    "own, reason",
    [
        # Exactly `scan_reach` away and exactly `scan_min_power`: worth it.
        (marines(2, y=20.0), "scan_hidden_enemy"),
        (marines(2, y=19.9), "no_army_near_hidden"),
        (marines(1), "no_army_near_hidden"),
        ((), "no_army_near_hidden"),
    ],
)
def test_a_scan_needs_the_army_that_will_shoot(own, reason) -> None:
    result = plan(Detection(), enemies=(lurker(),), own=own)

    assert result.reason == reason
    assert (result.scan is not None) == (reason == "scan_hidden_enemy")


@pytest.mark.parametrize(
    "structures", [(orbital(energy=49.9),), (orbital(ready=False),), ()]
)
def test_no_scan_without_an_orbitals_energy(structures) -> None:
    result = plan(Detection(), enemies=(lurker(),), own=marines(), structures=structures)

    assert (result.scan, result.reason) == (None, "no_scan_energy")


def test_the_scan_goes_where_most_army_is_then_most_is_revealed_then_lowest_tag() -> None:
    army = (*marines(3, x=30), *marines(4, x=50, first=300))
    result = plan(Detection(), enemies=(lurker(900, 30, 30), lurker(901, 50, 30)), own=army)
    assert result.scan == Point2((50.0, 30.0))

    # The same army near each; a scan at 901 also reveals 902, which is
    # exactly `scan_reach` from the army at (50, 24) too.
    army = (*marines(3, x=20), *marines(3, x=50, first=300))
    enemies = (lurker(900, 20, 30), lurker(901, 50, 30), lurker(902, 58, 30))
    result = plan(Detection(), enemies=enemies, own=army)
    assert result.scan == Point2((50.0, 30.0))

    result = plan(Detection(), enemies=(lurker(901, 50, 30), lurker(900, 20, 30)), own=army)
    assert result.scan == Point2((20.0, 30.0))


def test_a_detected_unit_is_no_scan_but_still_says_the_enemy_cloaks() -> None:
    detected = unit_view(FakeUnit(900, LURKER, 30, 30, burrowed=True, revealed=True), lambda _: 2)
    assert (detected.is_cloaked, detected.is_hidden) == (True, False)
    model = AwarenessModel()

    seen = model.infer(attention(time=400.0, own_units=marines(), enemy_units=(detected,)))
    frame = attention(time=401.0, own_units=marines())
    later = model.infer(frame)

    assert (seen.cloak_seen_at, seen.hidden_contacts) == (400.0, ())
    assert later.cloak_seen_at == 400.0
    result = Detection().plan(frame, later)
    assert (result.scan, result.reason) == (None, "no_hidden_enemy")
    assert result.energy_reserve == DetectionConfig().scan_reserve


def test_attention_reads_cloak_burrow_detection_and_energy() -> None:
    def supply(_):
        return 1.0

    dark_templar = FakeUnit(1, UnitTypeId.DARKTEMPLAR, 0, 0, cloaked=True)
    assert unit_view(dark_templar, supply).is_hidden
    assert unit_view(FakeUnit(1, LURKER, 0, 0, burrowed=True), supply).is_hidden
    plain = unit_view(FakeUnit(1, UnitTypeId.ZERGLING, 0, 0), supply)
    assert (plain.is_cloaked, plain.is_hidden) == (False, False)
    assert unit_view(FakeUnit(1, ORBITAL, 0, 0, energy=75.0), supply).energy == 75.0


def test_only_hidden_contacts_in_sight_count() -> None:
    model = AwarenessModel()
    model.infer(attention(time=100.0, enemy_units=(lurker(),)))

    remembered = model.infer(attention(time=101.0))

    assert [contact.tag for contact in remembered.contacts] == [900]
    assert remembered.hidden_contacts == ()
    assert remembered.cloak_seen_at == 100.0


def test_a_burrowed_worker_is_no_army_cloak() -> None:
    drone = unit(1, UnitTypeId.DRONEBURROWED, worker=True, hidden=True)

    state = AwarenessModel().infer(attention(time=100.0, enemy_units=(drone,)))

    assert state.cloak_seen_at is None


@pytest.mark.parametrize(
    "field", ["scan_reach", "scan_radius", "turret_cover", "scan_min_power", "scan_reserve"]
)
def test_invalid_detection_config_is_rejected(field) -> None:
    with pytest.raises(ValueError):
        DetectionConfig(**{field: -1.0})


def body_bot(*energies: float) -> FakeBot:
    bot = FakeBot()
    bot.structures = [
        FakeUnit(10 + index, ORBITAL, 10.5, 10.5, dps=0.0, structure=True, energy=energy)
        for index, energy in enumerate(energies)
    ]
    return bot


def detection_plan(**kw) -> DetectionPlan:
    values = dict(scan=None, turrets=(), engineering_bay=False, energy_reserve=0.0, reason="test")
    values.update(kw)
    return DetectionPlan(**values)


def test_the_orbital_with_most_energy_scans() -> None:
    bot = body_bot(60.0, 120.0, 120.0)
    target = Point2((30, 30))

    report = detection_behavior.execute(bot, detection_plan(scan=target))

    assert report.scanned_by == 11
    assert bot.structures[1].commands == [(AbilityId.SCANNERSWEEP_SCAN, target)]
    assert bot.structures[0].commands == bot.structures[2].commands == []

    bot = body_bot(49.0)
    assert detection_behavior.execute(bot, detection_plan(scan=target)).scanned_by is None
    assert bot.structures[0].commands == []


def test_orbitals_keep_a_scans_energy_and_the_scanning_one_drops_no_mule() -> None:
    field = FakeUnit(20, UnitTypeId.MINERALFIELD, 17, 10, dps=0.0, minerals=900)
    bot = body_bot(99.9, 100.0, 150.0)
    bot.townhalls = list(bot.structures)
    bot.mineral_field = [field]

    economy_behavior.execute(bot, planned(), energy_reserve=50.0, busy=frozenset({12}))

    mule = (AbilityId.CALLDOWNMULE_CALLDOWNMULE, field)
    assert [structure.commands for structure in bot.structures] == [[], [mule], []]


def test_an_engineering_bay_goes_before_the_turrets() -> None:
    bot = FakeBot()
    bot.minerals = 125

    report = detection_behavior.execute(
        bot, detection_plan(turrets=(MAIN.position,), engineering_bay=True)
    )

    (ebay,) = bot.registered
    assert isinstance(ebay, BuildStructure)
    assert (ebay.structure_id, ebay.to_count) == (UnitTypeId.ENGINEERINGBAY, 1)
    assert report.building == ("ENGINEERINGBAY",)


def test_a_turret_goes_to_the_expansion_nearest_the_first_base_that_needs_one() -> None:
    bot = FakeBot()
    bot.minerals = 100
    near_natural = Point2((31.0, 13.0))

    report = detection_behavior.execute(bot, detection_plan(turrets=(near_natural, MAIN.position)))

    (turret,) = bot.registered
    assert turret.structure_id is UnitTypeId.MISSILETURRET
    assert turret.base_location == MAP.expansions[1]
    assert turret.closest_to == near_natural
    assert turret.missile_turret and not turret.find_alternative
    assert report.building == ("MISSILETURRET",)

    bot = FakeBot()
    bot.minerals = 99
    report = detection_behavior.execute(bot, detection_plan(turrets=(MAIN.position,)))
    assert report == detection_behavior.DetectionReport()
    assert bot.registered == []


def test_a_burrowed_lurker_by_the_army_is_scanned_and_the_log_follows() -> None:
    logger = FakeLogger()
    bot = FakeBot()
    bot.time = 771.0
    bot.units = [FakeUnit(200 + index, UnitTypeId.MARINE, 60, 82) for index in range(4)]
    base = FakeUnit(1, ORBITAL, 10.5, 10.5, dps=0.0, structure=True, energy=150.0)
    bot.structures = [base]
    bot.townhalls = [base]
    bot.mineral_field = [FakeUnit(20, UnitTypeId.MINERALFIELD, 17, 10, dps=0.0, minerals=900)]
    bot.enemy_units = [
        FakeUnit(900, LURKER, 60.0, 90.0, dps=20.0, hit_points=200.0, burrowed=True)
    ]

    frame = play_frame(bot, 0, Layers(map_view=MAP, logs=Logs(logger)))

    target = Point2((60.0, 90.0))
    assert frame.detection.scan == target
    assert frame.detected.scanned_by == 1
    # With 100 energy left, the scanning Orbital drops no MULE this frame.
    assert base.commands == [(AbilityId.SCANNERSWEEP_SCAN, target)]
    (planned_event,) = logger.named("behavior.detection_planned")
    data = planned_event["data"]
    assert (data["scan"], data["scanned_by"], data["reason"]) == (
        [60.0, 90.0],
        1,
        "scan_hidden_enemy",
    )
    assert data["turrets"] == [[10.5, 10.5]]
    assert data["engineering_bay"]
    assert data["building"] == ["ENGINEERINGBAY"]
    assert data["energy_reserve"] == 50.0
    (updated,) = logger.named("awareness.updated")
    assert updated["data"]["hidden_contacts"] == [900]
    assert updated["data"]["cloak_seen_at"] == 771.0
    assert updated["data"]["strongest_contacts"][0]["hidden"]
    (observed,) = logger.named("attention.observed")
    assert observed["data"]["structures"] == {"ORBITALCOMMAND": 1}

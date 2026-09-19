from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ElementTree

import pytest
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.awareness import AwarenessModel
from bot.body.engine import Engine
from bot.ego.planners.military import army_fallback
from bot.ego.planners.military.defense import DefensePlanner
from bot.ego.strategy import StrategyModel
from bot.logs import (
    ChangeGate,
    JsonlLogger,
    Overlay,
    OverlayConfig,
    SnapshotConfig,
    SnapshotExporter,
    render_svg,
)
from bot.logs.overlay import influence_color, thin
from bot.logs.snapshot import snapshot_filename

from .fakes import MAP, FakeBot, FakeLogger, attention, unit

SVG = "{http://www.w3.org/2000/svg}"


def frame_layers(time: float = 0.0):
    frame = attention(
        time=time,
        # The Tank alone answers the Zergling, so both owners are drawn.
        own_units=(unit(1, x=22, y=20), unit(2, UnitTypeId.SIEGETANK, 20, 20, power=2.8)),
        enemy_units=(
            unit(90, UnitTypeId.ZERGLING, 14, 11, power=0.9),
            unit(91, UnitTypeId.ROACH, 40, 40, power=1.5),
        ),
        enemy_structures=(unit(95, UnitTypeId.HATCHERY, 53, 53, power=0.0, structure=True),),
    )
    awareness = AwarenessModel().infer(frame)
    strategy = StrategyModel().decide(frame, awareness)
    proposals = DefensePlanner().plan(
        frame, awareness, strategy
    ) + army_fallback.ArmyFallbackPlanner().plan(frame, awareness, strategy)
    return frame, awareness, strategy, Engine().allocate(frame, proposals)


def test_the_jsonl_logger_writes_the_envelope_and_rejects_non_json(tmp_path) -> None:
    logger = JsonlLogger(tmp_path, session_name="game", run_id="run-1")
    logger.event("game.started", component="logs", game_time=0.0, data={"map": "X"})
    logger.begin_frame(4)
    logger.event("strategy.decided", component="strategy", game_time=1.5, data={"danger": math.nan})
    logger.end_frame()
    logger.close()

    first, second = (
        json.loads(line) for line in logger.path.read_text(encoding="utf-8").splitlines()
    )
    assert first == {
        "schema": 4,
        "run": "run-1",
        "seq": 1,
        "iteration": None,
        "event": "game.started",
        "component": "logs",
        "game_time": 0.0,
        "data": {"map": "X"},
    }
    assert second["seq"] == 2 and second["iteration"] == 4
    assert second["event"] == "logging.record_rejected"
    assert second["data"]["rejected_event"] == "strategy.decided"


def test_a_change_gate_lets_out_changes_and_heartbeats() -> None:
    gate = ChangeGate(heartbeat=10.0)

    assert gate.admit("a", now=0.0)
    assert not gate.admit("a", now=5.0)
    assert gate.admit("b", now=6.0)
    assert not gate.admit("b", now=15.0)
    assert gate.admit("b", now=16.0)
    quiet = ChangeGate()
    assert quiet.admit("x", now=0.0)
    assert not quiet.admit("x", now=100.0)


def test_the_svg_snapshot_is_valid_deterministic_and_escaped() -> None:
    layers = frame_layers()

    svg = render_svg(*layers)
    root = ElementTree.fromstring(svg.encode("utf-8"))

    groups = {group.get("id") for group in root.iter(f"{SVG}g")}
    assert groups >= {"threat", "influence", "bases", "contacts", "army", "targets", "panel"}
    assert svg == render_svg(*layers)
    contacts = [c.get("data-contact") for c in root.iter(f"{SVG}circle") if c.get("data-contact")]
    assert contacts == ["visible", "visible"]
    owners = sorted(c.get("data-owner") for c in root.iter(f"{SVG}circle") if c.get("data-owner"))
    assert owners == ["core_army", "defense"]


def test_snapshots_follow_the_interval_and_objective_changes(tmp_path) -> None:
    logger = FakeLogger()
    exporter = SnapshotExporter(
        config=SnapshotConfig(enabled=True, interval_seconds=30.0),
        directory=tmp_path,
        logger=logger,
    )
    frame, awareness, strategy, result = frame_layers()

    assert not exporter.capture(frame, awareness, strategy, result)
    later = attention(time=31.0)
    assert exporter.capture(later, awareness, strategy, result)
    assert (tmp_path / "field-0031.svg").is_file()
    assert logger.named("logs.snapshot_written")[0]["data"]["trigger"] == "interval"
    assert snapshot_filename(12.25) == "field-0012-250.svg"


def test_a_failing_snapshot_is_logged_not_raised() -> None:
    logger = FakeLogger()
    exporter = SnapshotExporter(
        config=SnapshotConfig(enabled=True, interval_seconds=1.0), logger=logger
    )
    _, awareness, strategy, result = frame_layers()

    assert not exporter.capture(attention(time=2.0), awareness, strategy, result)
    assert logger.named("logs.snapshot_failed")


def test_the_overlay_draws_only_when_enabled_and_thins_the_field() -> None:
    frame, awareness, strategy, result = frame_layers()
    bot = FakeBot()

    assert Overlay().render(bot, frame, awareness, strategy, result) == 0
    assert bot.client.spheres == []

    every = Overlay(OverlayConfig(enabled=True, draw_spacing=None)).render(
        bot, frame, awareness, strategy, result
    )
    thinned = Overlay(OverlayConfig(enabled=True, draw_spacing=8.0)).render(
        FakeBot(), frame, awareness, strategy, result
    )
    assert every == len(MAP.lattice)
    assert 0 < thinned < every
    assert bot.client.world_text and bot.client.screen_text


def test_thinning_keeps_a_regular_grid() -> None:
    positions = tuple(Point2((x + 0.5, y + 0.5)) for y in range(0, 16, 2) for x in range(0, 16, 2))

    kept = [positions[index] for index in thin(positions, 2.0, 4.0)]

    assert len(kept) == 16
    assert all(round(p.x - 0.5) % 4 == 0 and round(p.y - 0.5) % 4 == 0 for p in kept)


@pytest.mark.parametrize(
    "support, enemy, threat", [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 1), (0, 0, 1)]
)
def test_influence_colors_are_valid_rgb(support, enemy, threat) -> None:
    assert all(0 <= channel <= 255 for channel in influence_color(support, enemy, threat))

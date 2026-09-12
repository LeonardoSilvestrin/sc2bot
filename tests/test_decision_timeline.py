"""Decision Timeline logic, run in a real headless Chromium-family browser.

The viewer is a standalone page, so its model is JavaScript. These tests load
the same ``logs/viewer/*.js`` files the page loads and skip when no
Chrome, Chromium or Edge is installed.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

MODULES = Path(__file__).parents[1] / "logs" / "viewer"
SCRIPTS = ("timeline_model.js", "diagnostics.js", "snapshots.js")

_BROWSER_CANDIDATES = (
    "chrome",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "msedge",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
)


def _browser() -> str | None:
    override = os.environ.get("VIEWER_TEST_BROWSER")
    if override:
        return override
    for candidate in _BROWSER_CANDIDATES:
        found = shutil.which(candidate) or (
            candidate if Path(candidate).is_file() else None
        )
        if found:
            return found
    return None


BROWSER = _browser()
pytestmark = pytest.mark.skipif(BROWSER is None, reason="no Chromium-family browser")


def run_js(tmp_path: Path, body: str) -> object:
    """Evaluate ``body`` (a function body returning JSON-able data)."""

    scripts = "".join(
        f'<script src="{(MODULES / name).as_uri()}"></script>' for name in SCRIPTS
    )
    page = tmp_path / "harness.html"
    page.write_text(
        "<!doctype html><body><pre id=out></pre>"
        f"{scripts}<script>"
        "const out = document.getElementById('out');"
        "try { out.textContent = JSON.stringify({ok: (function () {"
        f"{body}"
        "})()}); } catch (error) {"
        " out.textContent = JSON.stringify({error: String(error.stack)}); }"
        "</script></body>",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            str(BROWSER),
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-first-run",
            "--allow-file-access-from-files",
            f"--user-data-dir={tmp_path / 'profile'}",
            "--dump-dom",
            page.as_uri(),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )
    match = re.search(r"<pre id=\"out\">(.*?)</pre>", completed.stdout, re.S)
    assert match, f"browser produced no result: {completed.stderr[-2000:]}"
    result = json.loads(html.unescape(match.group(1)))
    assert "error" not in result, result.get("error")
    return result["ok"]


def records_js(records: list[dict]) -> str:
    return (
        f"const records = {json.dumps(records)}"
        ".map(r => ({component: 'test', data: {}, ...r}));"
    )


def knowledge(time: float, posture: str = "BALANCED", **threat: float) -> dict:
    return {
        "event": "knowledge.updated",
        "component": "world.awareness",
        "game_time": time,
        "data": {
            "posture": posture,
            "relative_strength": {"score": threat.get("score", 0.0)},
            "threat": {"near_own_base_enemy_combat_units": threat.get("near_base", 0)},
        },
    }


def strategy(time: float, objective: str, previous: str | None = None, **extra) -> dict:
    return {
        "event": "strategy.updated",
        "component": "strategy.director",
        "game_time": time,
        "data": {
            "objective": objective,
            "previous_objective": previous,
            "confidence": 0.6,
            "inputs": {"military_edge": -0.4, "immediate_threat": 0.7},
            **extra,
        },
    }


def mission(time: float, event: str, mission_id: str, kind: str, status: str) -> dict:
    return {
        "event": event,
        "component": "engine.missions.controller",
        "game_time": time,
        "data": {
            "mission_id": mission_id,
            "mission_kind": kind,
            "status": status,
            "reason": "test",
        },
    }


def behavior(time: float, mission_id: str, state: str) -> dict:
    return {
        "event": "behavior.state_changed",
        "component": "behavior.map_control",
        "game_time": time,
        "data": {"mission_id": mission_id, "state": state, "reason": "test"},
    }


def test_state_at_time_holds_the_last_value(tmp_path: Path) -> None:
    records = [knowledge(100, "BALANCED"), knowledge(150, "DEFENSE")]

    result = run_js(
        tmp_path,
        records_js(records)
        + """
        const model = SC2Timeline.buildDecisionTimeline(records);
        const track = model.t.macroPosture;
        return [50, 100, 130, 150, 170].map(t => SC2Timeline.valueAt(track, t) ?? null);
        """,
    )

    assert result == [None, "BALANCED", "BALANCED", "DEFENSE", "DEFENSE"]


def test_unchanged_heartbeats_do_not_create_changes(tmp_path: Path) -> None:
    records = [knowledge(t, "BALANCED") for t in (0, 10, 20)] + [
        knowledge(30, "DEFENSE")
    ]

    result = run_js(
        tmp_path,
        records_js(records)
        + """
        const model = SC2Timeline.buildDecisionTimeline(records);
        return model.t.macroPosture.points.map(p => [p.t, p.value]);
        """,
    )

    assert result == [[0, "BALANCED"], [30, "DEFENSE"]]


def test_strategy_transitions_are_detected_and_marked_shadow(tmp_path: Path) -> None:
    records = [
        strategy(200, "RECOVER"),
        strategy(210, "RECOVER"),
        strategy(248, "STABILIZE", previous="RECOVER"),
    ]

    result = run_js(
        tmp_path,
        records_js(records)
        + """
        const model = SC2Timeline.buildDecisionTimeline(records);
        const transitions = SC2Timeline.strategyTransitions(model);
        const cause = SC2Timeline.causeOf(model, transitions[0]);
        return {
          strategy: model.strategy,
          transitions: transitions.map(t => [t.t, t.from, t.to, t.shadow]),
          inputs: cause.strategyInputs.map(i => i.signal),
        };
        """,
    )

    assert result["strategy"] == {"available": True, "shadow": True}
    assert result["transitions"] == [[248, "RECOVER", "STABILIZE", True]]
    assert result["inputs"] == ["military_edge", "immediate_threat"]


def test_strategy_is_live_only_when_explicitly_not_shadow(tmp_path: Path) -> None:
    records = [strategy(10, "PRESSURE", shadow=False)]

    result = run_js(
        tmp_path,
        records_js(records)
        + "return SC2Timeline.buildDecisionTimeline(records).strategy;",
    )

    assert result == {"available": True, "shadow": False}


def test_cause_shows_the_signals_that_changed(tmp_path: Path) -> None:
    records = [
        knowledge(240, "BALANCED", near_base=0, score=-0.2),
        knowledge(248, "DEFENSE", near_base=7, score=-0.2),
    ]

    result = run_js(
        tmp_path,
        records_js(records)
        + """
        const model = SC2Timeline.buildDecisionTimeline(records);
        const change = SC2Timeline.transitions(model).find(t => t.to === "DEFENSE");
        const cause = SC2Timeline.causeOf(model, change);
        return cause.signals.map(s => [s.signal, s.before, s.after, s.changed]);
        """,
    )

    assert ["enemy_near_base", "0", "7", True] in result
    assert ["macro_posture", "BALANCED", "DEFENSE", True] in result
    assert ["relative_strength", "-0.20", "-0.20", False] in result


def test_snapshot_matching_picks_the_temporally_nearest(tmp_path: Path) -> None:
    result = run_js(
        tmp_path,
        """
        const name = t => `territory-${String(t).padStart(4, "0")}.svg`;
        const logged = [30, 240, 270].map(t => ({
          event: "debug.spatial_snapshot_written", game_time: t,
          data: {path: `C:\\\\logs\\\\game\\\\spatial\\\\${name(t)}`},
        }));
        const files = [
          {name: "territory-0240.svg"},
          {name: "territory-0250-500.svg"},
          {name: "latest.svg"},
        ];
        const index = SC2Snapshots.buildSnapshotIndex(logged, files);
        return {
          index: index.map(s => [s.t, s.name, Boolean(s.file)]),
          at245: SC2Snapshots.nearest(index, 245).name,
          at262: SC2Snapshots.nearest(index, 262).name,
          at1000: SC2Snapshots.nearest(index, 1000).name,
          tie: SC2Snapshots.nearest([{t: 240}, {t: 250}], 245).t,
          empty: SC2Snapshots.nearest([], 245) ?? null,
        };
        """,
    )

    assert result["index"] == [
        [30, "territory-0030.svg", False],
        [240, "territory-0240.svg", True],
        [250.5, "territory-0250-500.svg", True],
        [270, "territory-0270.svg", False],
    ]
    assert result["at245"] == "territory-0240.svg"
    assert result["at262"] == "territory-0270.svg"
    assert result["at1000"] == "territory-0270.svg"
    assert result["tie"] == 240
    assert result["empty"] is None


def test_logs_without_strategy_still_build_every_other_track(tmp_path: Path) -> None:
    records = [
        {"event": "game.started", "game_time": 0, "data": {"map": "Test"}},
        knowledge(10, "BALANCED"),
        {
            "event": "standing.updated",
            "game_time": 10,
            "data": {"combat_posture": "TURTLE"},
        },
        {"event": "attention.snapshot", "game_time": 12, "data": {}},
        mission(20, "mission_started", "mission-0001", "HOLD_RALLY", "ACTIVE"),
    ]

    result = run_js(
        tmp_path,
        records_js(records)
        + """
        const model = SC2Timeline.buildDecisionTimeline(records);
        const state = SC2Timeline.snapshotAt(model, 30);
        return {
          strategy: model.strategy,
          objective: state.strategy ?? null,
          macro: state.macroPosture,
          combat: state.combatPosture,
          army: state.armyBelief ?? null,
          missions: state.missions.map(m => [m.item.id, m.status]),
          diagnostics: SC2Diagnostics.runDiagnostics(model).length,
        };
        """,
    )

    assert result == {
        "strategy": {"available": False, "shadow": False},
        "objective": None,
        "macro": "BALANCED",
        "combat": "TURTLE",
        "army": None,
        "missions": [["mission-0001", "ACTIVE"]],
        "diagnostics": 0,
    }


def test_stabilize_with_map_control_active_is_diagnosed(tmp_path: Path) -> None:
    records = [
        strategy(100, "BUILD_ADVANTAGE"),
        mission(120, "mission_started", "mission-0004", "MAP_CONTROL", "ACTIVE"),
        behavior(120, "mission-0004", "PATROL"),
        strategy(150, "STABILIZE", previous="BUILD_ADVANTAGE"),
        behavior(170, "mission-0004", "HOLDING_HOME"),
        {"event": "game.ended", "game_time": 200, "data": {}},
    ]

    result = run_js(
        tmp_path,
        records_js(records)
        + """
        const model = SC2Timeline.buildDecisionTimeline(records);
        return SC2Diagnostics.runDiagnostics(model)
          .map(d => [d.rule, d.severity, d.start, d.end, d.title]);
        """,
    )

    assert result == [
        [
            "strategy_defensive_vs_map_control",
            "warning",
            150,
            170,
            "STABILIZE [shadow] + MAP_CONTROL engaged",
        ]
    ]


def test_turtle_and_behind_with_map_control_patrol_is_diagnosed(tmp_path: Path) -> None:
    # The rush game: standing already TURTLE and the army BEHIND, macro still
    # BALANCED, a Hellion sent on map control until strategic danger recalls it.
    records = [
        knowledge(118, "BALANCED", score=-0.6),
        {
            "event": "awareness.world_belief",
            "game_time": 118,
            "data": {"army": {"stable": "BEHIND"}},
        },
        {
            "event": "standing.updated",
            "game_time": 120,
            "data": {"combat_posture": "TURTLE"},
        },
        mission(246, "mission_started", "mission-0004", "MAP_CONTROL", "ACTIVE"),
        behavior(246, "mission-0004", "PATROL"),
        knowledge(248, "DEFENSE", score=-0.6, near_base=1),
        behavior(248, "mission-0004", "RETREAT"),
        {"event": "game.ended", "game_time": 300, "data": {}},
    ]

    result = run_js(
        tmp_path,
        records_js(records)
        + """
        const model = SC2Timeline.buildDecisionTimeline(records);
        const diagnostics = SC2Diagnostics.runDiagnostics(model);
        return {
          found: diagnostics.map(d => [d.rule, d.start, d.end, d.title]),
          at247: SC2Diagnostics.diagnosticsAt(diagnostics, 247).map(d => d.rule),
          at260: SC2Diagnostics.diagnosticsAt(diagnostics, 260).map(d => d.rule),
        };
        """,
    )

    assert result["found"] == [
        [
            "defensive_standing_vs_map_control",
            246,
            248,
            "TURTLE + army BEHIND + MAP_CONTROL engaged",
        ]
    ]
    assert result["at247"] == ["defensive_standing_vs_map_control"]
    assert result["at260"] == []


def test_enemy_at_base_without_active_defense_is_diagnosed(tmp_path: Path) -> None:
    records = [
        knowledge(10, "BALANCED", near_base=0),
        mission(20, "mission_blocked", "mission-0006", "DEFENSE", "BLOCKED"),
        knowledge(21, "DEFENSE", near_base=7),
        mission(30, "mission_started", "mission-0006", "DEFENSE", "ACTIVE"),
        {"event": "game.ended", "game_time": 60, "data": {}},
    ]

    result = run_js(
        tmp_path,
        records_js(records)
        + """
        const model = SC2Timeline.buildDecisionTimeline(records);
        return SC2Diagnostics.runDiagnostics(model).map(d => [d.rule, d.start, d.end]);
        """,
    )

    assert result == [["threat_near_base_no_defense", 21, 30]]

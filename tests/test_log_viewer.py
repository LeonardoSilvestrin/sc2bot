"""The log viewer: static safety checks, and a real run in headless Edge/Chrome
over a log produced by the frame flow."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from bot.logs import JsonlLogger, Logs, SnapshotConfig
from bot.main import Layers, play_frame

from .fakes import MAP
from .test_frame_flow import build_bot

VIEWER = Path(__file__).parents[1] / "logs" / "viewer.html"
MODULES = tuple(
    VIEWER.parent / "viewer" / name
    for name in ("timeline_model.js", "diagnostics.js", "snapshots.js", "decision_view.js")
)
# Model-only modules build no DOM at all.
PURE_MODULES = {"timeline_model.js", "diagnostics.js", "snapshots.js"}
CATALOG = (
    "game.started",
    "game.ended",
    "attention.observed",
    "awareness.updated",
    "strategy.decided",
    "behavior.proposed",
    "behavior.map_control_planned",
    "behavior.offense_planned",
    "behavior.missions_updated",
    "behavior.economy_planned",
    "engine.granted",
    "engine.commanded",
    "logs.frame_perf",
    "logs.snapshot_written",
)
BROWSERS = (
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
)


def test_the_viewer_reads_every_event_in_the_catalog() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in (VIEWER, *MODULES))

    for event in CATALOG:
        assert f'"{event}"' in source, event
    for module in MODULES:
        assert f'<script src="viewer/{module.name}"></script>' in VIEWER.read_text(encoding="utf-8")


def test_the_viewer_never_injects_log_values_as_html() -> None:
    for path in (VIEWER, *MODULES):
        source = path.read_text(encoding="utf-8")

        assert "innerHTML" not in source, path.name
        assert "outerHTML" not in source, path.name
        assert "insertAdjacentHTML" not in source, path.name
        assert "eval(" not in source, path.name
        assert "new Function" not in source, path.name
        assert "textContent" in source or path.name in PURE_MODULES, path.name


def _game_log(directory: Path) -> Path:
    logger = JsonlLogger(directory, session_name="game", run_id="viewer-test")
    logs = Logs(
        logger,
        snapshots=SnapshotConfig(enabled=True, interval_seconds=5.0),
        snapshot_directory=logger.session_directory / "spatial",
    )
    bot = build_bot(attackers=6)
    layers = Layers(map_view=MAP, logs=logs)
    logs.game_started(bot, MAP, layers.configs())
    for iteration, time in enumerate((0.0, 1.0, 2.0, 6.0, 12.0, 20.0, 31.0)):
        bot.time = time
        if time >= 12.0 and bot.enemy_units:
            bot.state.dead_units = {enemy.tag for enemy in bot.enemy_units}
            bot.enemy_units = []
        play_frame(bot, iteration, layers)
    logs.game_ended(31.5, "Result.Victory")
    return logger.path


def test_the_viewer_renders_a_real_log_in_a_browser(tmp_path: Path) -> None:
    browser = next((path for path in BROWSERS if path.is_file()), None)
    if browser is None:
        pytest.skip("no Chromium-family browser installed")
    log = _game_log(tmp_path / "logs")
    page_directory = tmp_path / "page"
    shutil.copytree(VIEWER.parent / "viewer", page_directory / "viewer")
    harness = (
        VIEWER.read_text(encoding="utf-8")
        .replace(
            "<head>",
            "<head><script>window.__errors = [];"
            "window.addEventListener('error', "
            "(e) => window.__errors.push(String(e.message)));</script>",
            1,
        )
        .replace(
            "</body>",
            "<script>(function () {\n"
            "  const out = document.createElement('pre'); out.id = 'harness';\n"
            "  try {\n"
            f"    loadText({json.dumps(log.read_text(encoding='utf-8'))}, 'game.jsonl', []);\n"
            "    const counts = {};\n"
            "    const views = ['summary', 'decision', 'events',\n"
            "      'attention', 'awareness', 'engine'];\n"
            "    for (const name of views) {\n"
            "      switchView(name);\n"
            "      const shown = document.getElementById('timeline');\n"
            "      counts[name] = shown.querySelectorAll('*').length;\n"
            "    }\n"
            "    switchView('decision');\n"
            "    const model = DecisionView.model();\n"
            "    counts.segments = document.querySelectorAll('.dt-seg').length;\n"
            "    counts.objectives = model.t.objective.points.map((p) => p.value);\n"
            "    counts.commandTracks = model.commandTracks.map((t) => t.owner);\n"
            "    counts.transitions = SC2Timeline.transitions(model).length;\n"
            "    switchView('summary');\n"
            "    counts.story = document.querySelectorAll('.story-item').length;\n"
            "    counts.errors = window.__errors;\n"
            "    out.textContent = 'HARNESS_OK ' + JSON.stringify(counts);\n"
            "  } catch (error) {\n"
            "    out.textContent = 'HARNESS_FAIL ' + (error && error.stack || error);\n"
            "  }\n"
            "  document.body.appendChild(out);\n"
            "})();</script></body>",
            1,
        )
    )
    page = page_directory / "viewer.html"
    page.write_text(harness, encoding="utf-8")

    completed = subprocess.run(
        [
            str(browser),
            "--headless",
            "--disable-gpu",
            "--no-first-run",
            f"--user-data-dir={tmp_path / 'profile'}",
            "--virtual-time-budget=5000",
            "--dump-dom",
            page.as_uri(),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )

    found = re.search(r'<pre id="harness">(HARNESS_\w+) (.*?)</pre>', completed.stdout, re.DOTALL)
    assert found is not None, completed.stderr[-2000:]
    outcome, payload = found.group(1), html.unescape(found.group(2))
    assert outcome == "HARNESS_OK", payload
    counts = json.loads(payload)
    assert counts["errors"] == []
    assert all(
        counts[name] > 0
        for name in ("summary", "decision", "events", "attention", "awareness", "engine")
    )
    assert counts["segments"] > 0
    assert counts["objectives"] == ["STABILIZE", "BUILD_ADVANTAGE"]
    assert set(counts["commandTracks"]) == {"defense", "core_army"}
    assert counts["transitions"] >= 3
    assert counts["story"] >= 4

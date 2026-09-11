from __future__ import annotations

from pathlib import Path

VIEWER = Path(__file__).parents[1] / "scripts" / "log_viewer.html"


def test_viewer_covers_the_structured_logging_catalog() -> None:
    html = VIEWER.read_text(encoding="utf-8")

    for event in (
        "observation.updated",
        "knowledge.updated",
        # Legacy aliases remain readable.
        "awareness.updated",
        "attention.world_state",
        "economic_proposal_created",
        "economic_proposal_rejected",
        "economic_proposal_deferred",
        "economic_action_admitted",
        "economic_action_pending",
        "economic_action_dispatched",
        "economic_action_confirmed",
        "economic_action_failed",
        "economic_action_timed_out",
        "economic_feedback_rejected",
    ):
        assert f'"{event}"' in html

    assert "function renderKnowledge()" in html
    assert "function renderObservation()" in html
    assert "function renderEconomyPanel()" in html
    assert 'id="stream-menu"' in html
    assert 'data-view="summary"' in html
    assert 'data-view="observation"' in html
    assert 'data-view="knowledge"' in html
    assert 'data-view="economy"' in html
    assert "function renderObservationPanel()" in html
    assert "function renderKnowledgePanel()" in html
    assert "function renderEconomySummary()" in html
    assert "function renderSummary()" in html
    assert "function renderSummaryPanel()" in html
    assert "function buildStoryMoments()" in html
    assert "function renderMetricCard(" in html
    assert '"behavior.state_changed"' in html
    assert '"standing.unassigned_units_persisting"' in html
    assert 'switchView("summary");' in html
    assert "item.planner" in html
    assert '"ego.mission_controller": "engine.missions.controller"' in html
    assert "buildStreams();" in html


def test_viewer_never_injects_log_values_as_html() -> None:
    html = VIEWER.read_text(encoding="utf-8")

    assert "innerHTML" not in html
    assert "outerHTML" not in html
    assert "insertAdjacentHTML" not in html
    assert "eval(" not in html
    assert "new Function" not in html
    assert "textContent" in html

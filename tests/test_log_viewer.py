from __future__ import annotations

from pathlib import Path

VIEWER = Path(__file__).parents[1] / "scripts" / "log_viewer.html"


def test_viewer_covers_the_structured_logging_catalog() -> None:
    html = VIEWER.read_text(encoding="utf-8")

    for event in (
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

    assert "function renderAwareness()" in html
    assert "function renderResources()" in html
    assert "function renderEconomyPanel()" in html
    assert 'id="stream-menu"' in html
    assert 'data-view="attention"' in html
    assert 'data-view="awareness"' in html
    assert 'data-view="economy"' in html
    assert "function renderAttentionPanel()" in html
    assert "function renderAwarenessPanel()" in html
    assert "function renderEconomySummary()" in html
    assert "item.planner" in html


def test_viewer_never_injects_log_values_as_html() -> None:
    html = VIEWER.read_text(encoding="utf-8")

    assert "innerHTML" not in html
    assert "outerHTML" not in html
    assert "insertAdjacentHTML" not in html
    assert "eval(" not in html
    assert "new Function" not in html
    assert "textContent" in html

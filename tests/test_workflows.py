"""The delivery gate: no workflow builds or uploads the bot before its tests and
lint have passed in the same job."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS = sorted((Path(__file__).parents[1] / ".github" / "workflows").glob("*.y*ml"))
# Steps that turn the checkout into something shipped.
DELIVERY_SCRIPTS = ("create_ladder_zip", "create_pyinstaller_exe", "upload_to_ai_arena")
DELIVERY_ACTIONS = ("actions/upload-artifact",)
# Step conditions that would still run after a failed gate.
AFTER_FAILURE = ("always()", "failure()", "cancelled()")


def _is_delivery(step: dict) -> bool:
    return any(script in step.get("run", "") for script in DELIVERY_SCRIPTS) or any(
        step.get("uses", "").startswith(action) for action in DELIVERY_ACTIONS
    )


def _first(steps: list[dict], command: str) -> int | None:
    return next((index for index, step in enumerate(steps) if command in step.get("run", "")), None)


def test_every_delivery_waits_for_tests_and_lint() -> None:
    delivering = 0
    for workflow in WORKFLOWS:
        for name, job in yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"].items():
            steps = job.get("steps", [])
            deliveries = [index for index, step in enumerate(steps) if _is_delivery(step)]
            if not deliveries:
                continue
            delivering += 1
            where = f"{workflow.name}:{name}"
            gates = {command: _first(steps, command) for command in ("pytest", "ruff check")}
            for command, index in gates.items():
                assert index is not None and index < deliveries[0], f"{where}: {command}"
                assert not steps[index].get("continue-on-error"), f"{where}: {command}"
            for index in deliveries:
                condition = str(steps[index].get("if", ""))
                assert not any(term in condition for term in AFTER_FAILURE), f"{where}: {condition}"
    assert delivering >= 2

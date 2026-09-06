"""Render a bot JSONL log as a readable timeline.

The runtime logs two very different kinds of events into the same file:
periodic telemetry (``attention.snapshot``, ``macro.build_order_progress``)
and one-shot narrative events (``proposal_*``, ``mission_*``, ``units_*``).
Reading the raw file top to bottom drowns the narrative in telemetry noise.

This renders one compact line per event, and by default skips the noisy
telemetry so what remains reads as a story: what was proposed, admitted,
assigned, and how it ended.

Usage:
    python scripts/read_log.py _botdev/logs/game-*.jsonl
    python scripts/read_log.py <path> --all              # include telemetry
    python scripts/read_log.py <path> --mission mission-0002
    python scripts/read_log.py <path> --summary           # mission lifecycle table
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

NARRATIVE_EVENTS = {
    "game.started",
    "game.ended",
    "proposal_created",
    "proposal_admitted",
    "proposal_rejected",
    "mission_queued",
    "mission_started",
    "mission_blocked",
    "units_assigned",
    "units_reassigned",
    "units_released",
    "mission_completed",
    "mission_failed",
    "mission_cancelled",
}


def format_time(seconds: float) -> str:
    minutes, secs = divmod(max(0.0, seconds), 60.0)
    return f"{int(minutes):02d}:{secs:05.2f}"


def format_event(record: dict[str, Any]) -> str:
    event = record["event"]
    data = record.get("data", {})
    mission_id = data.get("mission_id", "")
    reason = data.get("reason", "")
    extra: list[str] = []

    if event in ("proposal_created", "proposal_admitted", "proposal_rejected"):
        extra.append(f"target={data.get('target_key')}")
        extra.append(f"priority={data.get('priority')}")
        if event == "proposal_rejected":
            extra.append(f"conflict={data.get('conflicting_mission_id')}")
    elif event in (
        "mission_queued",
        "mission_started",
        "mission_blocked",
        "mission_completed",
        "mission_failed",
        "mission_cancelled",
    ):
        extra.append(f"status={data.get('status')}")
    elif event == "units_assigned":
        previous = data.get("previous_unit_tags") or []
        extra.append(f"units={data.get('unit_tags')}")
        if previous:
            extra.append(f"from={previous}")
    elif event == "units_reassigned":
        extra.append(f"units={data.get('unit_tags')}")
        extra.append(f"from={data.get('previous_unit_tags')}")
    elif event == "units_released":
        extra.append(f"units={data.get('unit_tags')}")
    elif event == "game.started":
        extra.append(f"map={data.get('map')}")
    elif event == "game.ended":
        extra.append(f"result={data.get('result')}")
    elif event == "macro.build_order_progress":
        extra.append(f"step={data.get('step')}/{data.get('total_steps')}")
        extra.append(f"command={data.get('command')}")
        extra.append(f"completed={data.get('completed')}")
    elif event == "attention.snapshot":
        extra.append(f"minerals={data.get('minerals')}")
        extra.append(f"vespene={data.get('vespene')}")
        extra.append(f"supply={data.get('supply')}")
        extra.append(f"own={data.get('own_combat_units')}")
        extra.append(f"enemy_known={data.get('known_enemy_combat_units')}")
        extra.append(f"strength={data.get('strength_score')}")
    else:
        extra = [f"{key}={value}" for key, value in data.items() if key != "reason"]

    header = f"[{format_time(record['game_time'])}] {event:<20}"
    if mission_id:
        header += f" {mission_id:<13}"
    elif event in NARRATIVE_EVENTS:
        header += " " * 14
    if reason and event not in ("game.started", "game.ended"):
        header += f" {reason:<38}"
    return (header + "  " + " ".join(extra)).rstrip()


def load_records(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def summarize_missions(records: Iterable[dict[str, Any]]) -> str:
    missions: dict[str, dict[str, Any]] = {}
    for record in records:
        data = record.get("data", {})
        mission_id = data.get("mission_id")
        if not mission_id:
            continue
        mission = missions.setdefault(
            mission_id,
            {"target": data.get("target_key"), "kind": data.get("mission_kind"), "events": []},
        )
        mission["events"].append((record["game_time"], record["event"], data.get("status")))

    lines = []
    for mission_id, info in missions.items():
        start = info["events"][0][0]
        end = info["events"][-1][0]
        final_status = next(
            (status for _, _, status in reversed(info["events"]) if status), "?"
        )
        lines.append(
            f"{mission_id:<13} {info['kind'] or '?':<8} target={info['target']:<16} "
            f"{format_time(start)}..{format_time(end)}  final={final_status}"
        )
    return "\n".join(lines) if lines else "(no missions in this log)"


DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "_botdev" / "logs"


def find_latest_log(directory: Path = DEFAULT_LOG_DIR) -> Path:
    candidates = sorted(directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise SystemExit(f"No .jsonl log files found in {directory}")
    return candidates[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "path",
        type=Path,
        nargs="?",
        default=None,
        help=f"Path to a .jsonl log file (defaults to the most recent file in {DEFAULT_LOG_DIR})",
    )
    parser.add_argument(
        "--all", action="store_true", help="Include telemetry events (attention.snapshot, macro.build_order_progress)"
    )
    parser.add_argument("--event", help="Only show events whose name contains this substring")
    parser.add_argument("--mission", help="Only show events for this mission_id")
    parser.add_argument("--summary", action="store_true", help="Print a one-line-per-mission lifecycle summary instead")
    args = parser.parse_args()

    path = args.path or find_latest_log()
    print(f"# {path}")
    records = load_records(path)

    if args.summary:
        print(summarize_missions(records))
        return

    for record in records:
        if not args.all and record["event"] not in NARRATIVE_EVENTS:
            continue
        if args.event and args.event not in record["event"]:
            continue
        if args.mission and record.get("data", {}).get("mission_id") != args.mission:
            continue
        print(format_event(record))


if __name__ == "__main__":
    main()

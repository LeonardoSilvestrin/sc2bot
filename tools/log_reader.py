from __future__ import annotations

import json
from pathlib import Path


KEYS = [
    ("first_depot", "plan_step_done"),
    ("first_barracks", "plan_step_done"),
    ("marine", "action_issued"),
]


def main(path: str):
    p = Path(path)
    events = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))

    def find_plan_step(name: str):
        for e in events:
            if e.get("event") != "plan_step_done":
                continue
            if (e.get("payload") or {}).get("name") == name:
                return e
        return None

    def find_first_train(unit_name: str):
        for e in events:
            if e.get("event") != "action_issued":
                continue
            do = (e.get("payload") or {}).get("do") or {}
            if do.get("train") == unit_name:
                return e
        return None

    depot = find_plan_step("first_depot")
    rax = find_plan_step("first_barracks")
    marine = find_first_train("MARINE")

    def fmt(e):
        if not e:
            return "—"
        meta = e.get("meta") or {}
        t = meta.get("t")
        it = meta.get("iter")
        return f"t={t:.1f}s iter={it}" if isinstance(t, (int, float)) else f"iter={it}"

    print("== Timings ==")
    print("Depot:", fmt(depot))
    print("Barracks:", fmt(rax))
    print("1st Marine train:", fmt(marine))


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python tools/summarize_log.py logs/game_xxx.jsonl")
        raise SystemExit(2)
    main(sys.argv[1])
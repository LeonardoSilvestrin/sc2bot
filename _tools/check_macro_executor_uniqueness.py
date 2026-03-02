from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
TASKS_DIR = ROOT / "bot" / "tasks" / "macro" / "tasks"
PLANNER_FILE = ROOT / "bot" / "planners" / "macro" / "orchestrator_planner.py"
EXECUTOR_FILE = TASKS_DIR / "macro_ares_executor_tick.py"


def fail(msg: str) -> None:
    print(f"[macro-guard] FAIL: {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"[macro-guard] OK: {msg}")


def check_planner() -> None:
    text = PLANNER_FILE.read_text(encoding="utf-8")
    banned = ("MacroSpendingTick", "MacroProductionTick", "MacroTechTick")
    found = [name for name in banned if name in text]
    if found:
        fail(f"planner references deprecated macro tasks: {', '.join(found)}")
    ok("planner does not reference deprecated macro tasks")


def check_tasks() -> None:
    register_sites: list[str] = []
    for path in sorted(TASKS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "register_behavior(" not in text:
            continue
        register_sites.append(str(path.relative_to(ROOT)))
        if path.resolve() != EXECUTOR_FILE.resolve():
            fail("register_behavior found outside executor: " + str(path.relative_to(ROOT)))
    if len(register_sites) != 1:
        fail(f"expected exactly 1 register_behavior site in macro tasks, found {len(register_sites)}")
    ok("macro tasks have a single register_behavior site")


def main() -> None:
    check_planner()
    check_tasks()
    print("[macro-guard] PASS")


if __name__ == "__main__":
    main()

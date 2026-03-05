from __future__ import annotations

# Awareness key ownership contract.
# Keep this small and explicit to avoid silent refactor breakages.

CONTRACTS: dict[str, dict[str, str]] = {
    "attention.*": {"writer": "sensors", "reader": "intel/control/planners/tasks"},
    "enemy.*": {"writer": "intel", "reader": "control/planners/tasks"},
    "strategy.parity.*": {"writer": "intel.game_parity", "reader": "control/planners/tasks"},
    "macro.desired.*": {"writer": "intel.*", "reader": "control/planners/tasks"},
    "macro.control.*": {"writer": "control.advantage_supervisor", "reader": "control/planners/tasks"},
    "macro.opening.done*": {"writer": "intel.opening_contract", "reader": "sensors/planners/control"},
    "macro.production.plan.*": {"writer": "planner.macro_orchestrator", "reader": "task.macro_production"},
    "macro.tech.plan.*": {"writer": "planner.macro_orchestrator", "reader": "task.macro_tech"},
    "macro.gas.*": {"writer": "planner.macro_orchestrator", "reader": "tasks.macro_executor/scv_housekeeping"},
    "macro.plan.*": {"writer": "planner.macro_orchestrator", "reader": "task.macro_executor"},
    "control.priority.*": {"writer": "control.priority_policy", "reader": "ego"},
    "ego.exec_budget.*": {"writer": "ego", "reader": "tasks"},
    "ops.*": {"writer": "ego/tasks", "reader": "sensors/planners/tasks/control"},
}


INVARIANTS: tuple[str, ...] = (
    "intel functions are pure and never issue game commands",
    "control modules compute priorities/reserves and never issue game commands",
    "planners emit proposals and never issue game commands",
    "tasks execute commands and must not write control.* keys",
)

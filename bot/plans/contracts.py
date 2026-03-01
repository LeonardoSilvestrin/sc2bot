from __future__ import annotations

# Awareness key ownership contract.
# Keep this small and explicit to avoid silent refactor breakages.

CONTRACTS: dict[str, dict[str, str]] = {
    "attention.*": {"writer": "sensors", "reader": "intel/control/planners/tasks"},
    "enemy.*": {"writer": "intel", "reader": "control/planners/tasks"},
    "strategy.parity.*": {"writer": "intel.game_parity", "reader": "planners/tasks"},
    "macro.desired.*": {"writer": "intel.my_army_composition", "reader": "control/planners/tasks"},
    "macro.opening.done*": {"writer": "runtime.self", "reader": "sensors/planners/control"},
    "macro.production.plan.*": {"writer": "planner.macro_orchestrator", "reader": "task.macro_production"},
    "macro.tech.plan.*": {"writer": "planner.macro_orchestrator", "reader": "task.macro_tech"},
    "macro.gas.*": {"writer": "control.priority_policy", "reader": "tasks.macro_spending/scv_housekeeping"},
    "macro.reserve.*": {"writer": "control.priority_policy", "reader": "macro tasks"},
    "control.priority.*": {"writer": "control.priority_policy", "reader": "ego"},
    "ops.*": {"writer": "ego", "reader": "sensors/tasks"},
}


INVARIANTS: tuple[str, ...] = (
    "intel functions are pure and never issue game commands",
    "control modules compute priorities/reserves and never issue game commands",
    "planners emit proposals and never issue game commands",
    "tasks execute commands and must not write control.* keys",
)

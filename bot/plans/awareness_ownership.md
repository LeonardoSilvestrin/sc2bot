# Awareness Ownership Map

## Current Prefix Ownership (high level)

- `macro.desired.*`
  - Writers:
    - `bot/intel/macro/desired_intel.py`
  - Readers:
    - strategy, planners, macro tasks

- `macro.control.*`
  - Writer:
    - `bot/intel/strategy/i2_CTRL_advantage_game_status_intel.py`
  - Readers:
    - prioritization intel, macro orchestrator planner

- `strategy.parity.*`
  - Writer:
    - `bot/intel/strategy/i1_game_parity_intel.py`
  - Readers:
    - strategy/control layer, planner, runtime diagnostics

- `control.priority.*`
  - Writers:
    - `bot/intel/ego/i1_PI_prioritization_intel.py`
    - `bot/planners/macro_orchestrator_planner.py` (lag signals)
    - `bot/mind/ego.py` (error traces)
  - Readers:
    - prioritization intel, planner, runtime diagnostics

- `macro.exec.*`
  - Writers:
    - `bot/planners/macro_orchestrator_planner.py`
    - `bot/tasks/macro/tasks/macro_ares_executor_tick.py`
  - Readers:
    - planner, task, prioritization intel

- `tech.exec.*`
  - Writers:
    - `bot/planners/macro_orchestrator_planner.py`
    - `bot/tasks/tech/tasks/tech_ares_executor_tick.py`
  - Readers:
    - planner, tech task

- `macro.opening.*`
  - Writers:
    - `bot/intel/enemy/opening_intel.py`
    - `bot/mind/self.py`
  - Readers:
    - desired intels, planner, sensors

- `strategy.advantage.*`
  - Readers:
    - `bot/intel/strategy/i2_CTRL_advantage_game_status_intel.py`
  - Writer:
    - none found in repository

## Hotspots (multi-writer / unclear ownership)

- `macro.exec.*` has 2 writers.
- `tech.exec.*` has 2 writers.
- `macro.opening.*` has 2 writers.
- `control.priority.*` is a mixed namespace (policy, lag metrics, errors).
- `strategy.advantage.*` has no in-repo writer.

## Recommended Directory Organization Rule

Organize by **awareness namespace written** (same spirit as `intel`):

- Modules writing `macro.desired.*` stay in `intel/macro/desired_intel.py`.
- Modules writing `macro.control.*` stay in `intel/strategy` (or `intel/macro/control` if consolidated later).
- Modules writing `control.priority.*` stay in `intel/ego`.
- Planners/tasks should be grouped by the namespace they **own as writer**:
  - `planners/macro/plan` (`macro.plan.*`)
  - `planners/macro/exec` (`macro.exec.*`) if planner is sole writer
  - `tasks/tech/exec` (`tech.exec.*`) if task is sole writer

## Proposed Ownership Cleanup (next refactor)

1. Make `macro.exec.*` single-writer (planner), move task-side status to `ops.macro.exec_runtime.*`.
2. Make `tech.exec.*` single-writer (planner), move task-side status to `ops.tech.exec_runtime.*`.
3. Make `macro.opening.*` single-writer (`intel/enemy/opening_intel.py`), move runtime sync cache to `ops.opening.sync.*`.
4. Split `control.priority.*` into:
   - `control.priority.*` (prioritization intel only)
   - `control.lag.*` (macro orchestrator lag signals)
   - `ops.priority.error.*` (ego errors)
5. Either add a writer for `strategy.advantage.*` or remove its usage from strategy control intel.

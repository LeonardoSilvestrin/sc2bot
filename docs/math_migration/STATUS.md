# Current status

Stabilization and auditability pass over the Strategy / StrategicIntent /
ControlObjective / Mission Policy integration, before any mathematical
migration. Rules: [PRINCIPLES.md](PRINCIPLES.md).

## Last completed commit

`refactor: remove prescriptive awareness transport` (Stage 4).

## Completed stages

- **Stage 0 -- control objective integration** (`9b70838`). The user's WIP
  was already committed as `ffce62d`; finished on top. `ControlMatch`
  (alignment >= 0.5); Map Control's anchor score split into `local_value`,
  `caution`, `strategic_value`, opportunity from local value alone.
- **Stage 1 -- explicit mission viability** (`25dba8d`). `MissionEvaluation`
  with raw/final utility, floor, `viable`, reason, priority only when viable
  (`is_viable`: utility > 0). Rejected candidates never reach the engine; a
  rejected standing responsibility is withdrawn via `declared_planners`.
- **Stage 2 -- causally reproducible decision trace** (`a80e313`). JSONL
  envelope (schema, run, seq, iteration, exact game time), strict JSON with a
  loud rejection record, enriched `game.started` (opening, build, config
  fingerprints, seed), `StrategicContext.revision` persisted as
  `strategy.context` before the first decision citing it, provenance on
  `mission.evaluated`, spatial selection summary, `mission.progressed`,
  logged `preemption_cost` faults, joinable causal-chain tests.
- **Stage 3 -- behavior-owned unit requirements** (`6870bdd`).
  - Removed: `CombatCapabilities`, `Capability`, `CapabilityRequirement`,
    `Suitability`, `UNIT_PROFILES`, `COMBAT_UNIT_TYPES`, `is_combat_unit`
    (`bot/domain/capabilities.py`, `profiles.py`); `CombatRole`
    (`engine/missions/roles.py`); `CapabilityAllocationLog`
    (`capability_log.py`); `UnitRequirement.capability`, `for_role`,
    `any_combat_unit`; allocator upgrades (`UnitUpgrade`, `upgrade_margin`);
    the `units_upgraded` / `capability_*` events;
    `docs/engine/capabilities.md`; `tests/test_combat_capabilities.py` and
    `tests/test_capability_allocation.py` (still-valid scenarios moved to
    `tests/test_unit_requirements.py`).
  - Kept: exclusive leases, minimum/desired counts, health/readiness/
    availability filters, supply budgets, per-type desirability, deterministic
    ordering, commitment windows, preemption and lifecycle cleanup.
  - Rosters: Standing's explicit `STANDING_ROSTER` (exactly the previous
    combat set: no unit loses its owner); Map Control's `PATROL_UNIT_TYPES`
    (Cyclone, Hellion, Marine, Marauder -- the ground units its loop, ground
    pathing and ground-threat retreat were written for) with a local
    preference Cyclone 1.0, Hellion 0.9, Marine/Marauder 0.6; raids, scout
    and Defense unchanged. `type_desirability` may only price requested types.
  - Map Control sizes its share from the whole army counted by physical facts
    (armed, not a worker), not from a profile table.
  - A test fails when a registered build's army contains a type with no
    roster decision (Standing roster or declared unarmed support).
- **Stage 4 -- no prescriptive transport through Awareness.**
  - Removed: `AwarenessSnapshot.macro_posture`; `bot/world/awareness/posture.py`,
    `bot/strategy/posture.py`, `bot/domain/` (last file: the `MacroPosture`
    enum); `AwarenessService`'s unused `defense_release_after`,
    `posture_min_hold`, `greed_safe_after` arguments; `posture` in
    `knowledge.updated`; `StrategyRuntime`'s legacy posture output.
  - Macro posture is macro's policy: `MacroPosture`, `MacroContext`,
    `MacroPostureConfig`, `MacroPostureDirector` in `bot/macro/posture.py`,
    rules and timings unchanged, each result now carrying a reason.
  - Transport: `bot/app/macro_context.py` (`MacroContextRuntime`) runs the
    director on Awareness readings, logs `macro.posture` (posture, previous,
    reason, inputs) on change, and passes `MacroContext` to
    `MacroPlanner.propose(attention, awareness, context)`. Its config is
    fingerprinted as `configs.macro_posture`.
  - Architecture tests: no intent/desired/objective/priority/posture field on
    an Awareness type; `bot.world` imports no Strategy, macro, behavior, app
    or domain; the Strategy core imports only itself and the standard library
    and never reaches behavior/engine/macro/app/adapters; the engine imports no
    Strategy, behavior or app; behavior and macro stay apart; no `bot/domain`
    directory and no `bot.domain` import.

## Tests and tooling

At Stage 4 (Windows, project `.venv`, Python 3.12):

- `pytest`: 818 passed.
- `ruff check bot tests`: clean.
- `mypy bot`: clean.
- `git diff --check`: clean.

Run with `.\.venv\Scripts\python.exe -m pytest` (the system `python` has no
pytest/ruff/mypy).

## Architectural decisions

- `ControlMatch` and its threshold are Strategy contract invariants.
- Map Control pulls its anchor with objective importance, not gap.
- Viability threshold stays 0.0 behind `is_viable`.
- Rejected standing work is withdrawn through existing standing
  reconciliation; the engine receives planner ids only.
- The JSONL envelope is the writer's job, frame scoping the port's; a
  serialization fault is written, never raised or coerced.
- Context revisions are assigned in `bot.app` by exact equality and persisted
  lazily before first use.
- No preferred/optional unit contract was introduced: a concrete roster plus a
  local per-type preference expresses every current behavior.
- Allocator shrink order now honors the requesting behavior's preference for
  every requirement (it used to apply only to capability requirements);
  equal preferences still go by distance, health and tag.
- Boundary change (Stage 4): macro posture moved from Awareness/Strategy into
  `bot.macro`, and `bot.app` became its transport. Reason: a posture prescribes
  how to spend, so it violated "Awareness describes", and Strategy only hosted
  it for compatibility. Replacement invariant: Awareness carries no
  prescription; macro receives its policy only as an explicit `MacroContext`
  argument; neither Awareness nor Strategy imports macro.
- The frame keeps its order: `MacroContextRuntime.update` runs at the start of
  the macro step, after the mission engine; its only inputs are the frame's
  Awareness readings.

## Known issues

- Behavior change: a held unit is no longer swapped for a better one. After a
  Bio -> Mech transition the patrol keeps its Marines until they die or the
  patrol shrinks, instead of upgrading to Cyclones.
- Map Control no longer requests Siege Tanks, Reapers or Banshees even when
  nothing else is available; the patrol can stay empty in such an army.
- A live FINITE mission is not withdrawn when its re-declared candidate is
  rejected.
- Build identity does not detect uncommitted changes; while macro follows the
  opening, `configs.macro` fingerprints `None`.
- State summaries still round; the log viewer does not display the new
  records.
- Logs recorded before Stage 4 carry posture in `knowledge.updated`; the
  viewer still reads it there when no `macro.posture` event exists.
- `MissionController` orders equal priorities by `admitted_at` only (Stage 5).
- Untracked `.codex-pytest-strategy/` and `.pytest-run-spatial-fix/` are
  permission-locked test-output directories not created by this pass; left
  untouched.

## Deferred work

- The mathematical migration itself. Recommended first: production
  demand/capacity (measurable quantities, localized seams).
- Retuning any weight: every number is still a first guess.
- Viewer support for the new records.

## Next stage

Stage 5 -- lock replacement seams and behavioral invariants: kernel replay
fixtures (Strategy, Mission Policy, spatial anchor, allocation), relational
invariants (utility monotonicity, control contribution, rejection, leases,
terminal missions, arbitration order, logged evaluation), and an explicit
deterministic `MissionController` tie-break with shuffled-input tests.

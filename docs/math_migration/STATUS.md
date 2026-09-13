# Current status

Stabilization and auditability pass over the Strategy / StrategicIntent /
ControlObjective / Mission Policy integration, before any mathematical
migration. Rules: [PRINCIPLES.md](PRINCIPLES.md).

## Last completed commit

`feat: make decision traces causally reproducible` (Stage 2).

## Completed stages

- **Stage 0 -- control objective integration** (`9b70838`). The unfinished
  consumer migration was already committed by the user as `ffce62d` (18
  files, +757/-106), so the worktree was clean; this stage finished it on top
  instead of rewriting it. `ControlMatch` (alignment >= 0.5) replaces the
  loose objective id/alignment pair; Map Control's anchor score is split into
  `local_value`, `caution` and `strategic_value`, and its opportunity is the
  local value alone.
- **Stage 1 -- explicit mission viability** (`25dba8d`). `evaluate_mission`
  returns a `MissionEvaluation` with raw/final utility, floor, `viable`,
  reason, and a priority only when viable (`is_viable`: utility > 0). Rejected
  candidates never reach `MissionController`; a rejected standing
  responsibility is withdrawn through `declared_planners`. Docs lost every
  fixed per-kind priority.
- **Stage 2 -- causally reproducible decision trace.**
  - JSONL envelope on every record: `schema` (2), `run`, `seq`, `iteration`
    (null outside a frame), exact `game_time`. The port gained
    `begin_frame`/`end_frame`; `FrameProcessor` brackets each frame.
  - Strict JSON: no `default=str`. A record that is not strict JSON becomes a
    `logging.record_rejected` fault record naming the event and the error.
    The test `FakeLogger` enforces strict JSON for every event any test emits.
  - `game.started` records the opening actually played, build identity
    (commit/branch from git's files, or explicitly unknown), a fingerprint of
    every decision-critical configuration plus one per config, and the RNG
    seed with its source (`generated`, `configured`, `external`).
  - `StrategicContext.revision`: increments only when intent or the control
    objective set changes materially. `StrategyRuntime.record_context()`
    persists the exact, complete context (objective, assessments with
    contributions, inputs, intent, every objective) once per revision as
    `strategy.context`; the frame calls it before the first policy decision.
  - `mission.evaluated` cites `context_revision`, `policy_model`
    (`linear_utility_v1`) and `policy_config` (fingerprint); decision values
    are logged at machine precision.
  - `map_control.spatial_candidates` adds candidate count, pool, rejection
    counts, runner-up, winning margin and an order-free candidate-set
    fingerprint.
  - `mission.progressed` on a change of an active mission's
    (outcome, reason); a raising or NaN `preemption_cost()` logs
    `mission.preemption_cost_failed` (first failure, then at most every 30 s
    with the suppressed count) before reading as 0.
  - Joinable causal-chain tests against a real JSONL file: context ->
    evaluation -> admission -> assignment -> progress, and context ->
    rejected evaluation -> nothing in the engine.

## Tests and tooling

At Stage 2 (Windows, project `.venv`, Python 3.12):

- `pytest`: 839 passed.
- `ruff check bot tests`: clean.
- `mypy bot`: clean.
- `git diff --check`: clean.

Run with `.\.venv\Scripts\python.exe -m pytest` (the system `python` has no
pytest/ruff/mypy).

## Architectural decisions

- `ControlMatch` and its threshold live in `bot.strategy.mission_policy`, so
  "an objective id implies a meaningful alignment" is a contract invariant.
- Map Control pulls its anchor with objective importance, not gap (the gap
  shrinks as the patrol arrives); the policy prices importance x gap.
- Contract 16 was already relaxed in `ffce62d`: only macro and the mission
  engine are kept out of territory.
- Viability threshold stays 0.0 behind `is_viable`; no evidence yet for a
  higher semantic minimum.
- Rejected standing work is withdrawn through the existing standing
  reconciliation; the engine only receives planner ids.
- The envelope is the writer's job (adapter), frame scoping the port's; no
  event sourcing. A serialization fault is written, not raised, so a bad
  record cannot stop a match, and never coerced.
- Context revisions are assigned in `bot.app` by exact dataclass equality of
  intent and objectives; Strategy's core stays hash- and I/O-free. The
  context is persisted lazily, before the first decision that cites it, so
  unreferenced revisions cost nothing.
- Configuration fingerprints and build identity live in
  `bot/app/run_identity.py`; unsupported config values are refused, not
  stringified. Build identity reads git files, never a subprocess.

## Known issues

- A live FINITE mission is not withdrawn when its re-declared candidate is
  rejected; it runs to its own end or timeout.
- Build identity does not detect uncommitted changes.
- While macro follows the opening, `configs.macro` fingerprints `None`; the
  opening name in `game.started` determines the profile.
- State summaries (observation, knowledge, standing, macro status, behavior
  plans) still round for readability; decision records do not.
- The log viewer does not yet display the envelope, `strategy.context`,
  `mission.evaluated`, `mission.progressed` or the spatial summary fields.
- Map Control and Standing still use the capability/role system in
  `bot/domain` (Stage 3).
- `AwarenessSnapshot.macro_posture` transports macro policy through
  Awareness (Stage 4).
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

Stage 3 -- replace the RPG capability model with behavior-owned concrete unit
requirements: remove `CombatCapabilities`, `CapabilityRequirement`,
`Suitability`, unit profiles, `CombatRole` and capability allocation
diagnostics/upgrades; each behavior names its supported unit types; keep
leases, counts, supply budgets, per-type desirability, commitment and
preemption.

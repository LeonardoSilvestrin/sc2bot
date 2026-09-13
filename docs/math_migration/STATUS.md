# Current status

Stabilization and auditability pass over the Strategy / StrategicIntent /
ControlObjective / Mission Policy integration, before any mathematical
migration. Rules: [PRINCIPLES.md](PRINCIPLES.md).

## Last completed commit

`fix: reject non-viable mission candidates` (Stage 1).

## Completed stages

- **Stage 0 -- control objective integration** (`9b70838`). The unfinished
  consumer migration was already committed by the user as `ffce62d` (18
  files, +757/-106), so the worktree was clean; this stage finished it on top
  instead of rewriting it.
  - `ControlMatch(objective_id, alignment)` replaces the loose
    `control_objective` / `control_alignment` pair on `MissionSignals`. A match
    exists only at `alignment >= MINIMUM_CONTROL_ALIGNMENT` (0.5).
  - Map Control's anchor evaluation (`evaluate_sample` ->
    `MapControlCandidate`) is split into `local_value`, `caution` and
    `strategic_value`. Strategy moves the anchor only through
    `strategic_value`; the patrol's `opportunity` is `local_value` alone.
  - Explicit tie-breaks for objective pull and travel origin.
  - Docs no longer call Strategy or territory regions shadow/unconsumed.
- **Stage 1 -- explicit mission viability.**
  - `evaluate_mission` returns a `MissionEvaluation`: every contribution,
    `raw_utility`, `urgency_floor`, final `utility`, `viable`, a
    machine-readable `reason`, `priority` only when viable, and the Strategy
    inputs it read (desirability, information desire, risk tolerance,
    control need).
  - Viability is one replaceable predicate, `is_viable`:
    `utility > MissionPolicyConfig.minimum_viable_utility` (0.0). The
    emergency floor applies first, so urgent defense stays viable with a
    negative raw utility. The fallback owner is always viable at 20.
  - `MissionRanker` proposes viable candidates only and logs one
    `mission.evaluated` per candidate, rejected ones included (no change
    gate; `mission.candidate` / `mission.ranked` are gone).
  - `MissionController.tick(declared_planners=...)`: a planner that declared
    work whose standing candidate was rejected has that standing mission
    cancelled (`standing_proposal_omitted`), so rejected work cannot keep
    units at an old priority. The engine receives planner ids only.
  - The test that blessed a worthless candidate outranking Standing is
    replaced by one asserting no worthless candidate can.
  - Every canonical doc that listed fixed per-kind priorities (contracts,
    engine/missions, behavior README, standing, scouting, defense, harass,
    base-security) now describes policy ranking and viability. `standing.md`
    also had pre-`ffce62d` anchor and posture sections (anchor now follows
    Strategy's home passage objective; posture no longer reads macro
    posture); corrected here.

## Tests and tooling

At Stage 1 (Windows, project `.venv`, Python 3.12):

- `pytest`: 804 passed.
- `ruff check bot tests`: clean.
- `mypy bot`: clean.
- `git diff --check`: clean.

Run with `.\.venv\Scripts\python.exe -m pytest` (the system `python` has no
pytest/ruff/mypy).

## Architectural decisions

- `ControlMatch` and its threshold live in `bot.strategy.mission_policy`, next
  to `MissionSignals`: the invariant "an objective id implies a meaningful
  alignment" is enforced by the contract, not by each planner.
- Map Control pulls its anchor with the objective's *importance*, not its
  gap: the gap shrinks as our own patrol arrives, which would argue the
  anchor away. The Mission Policy still prices importance x gap.
- Contract 16 was already relaxed in `ffce62d` (`ConsumerTests`): macro and
  the mission engine never read territory; Strategy and behaviors may.
- Viability threshold stays 0.0: no repository evidence justifies a higher
  semantic minimum yet. It is a config value behind `is_viable`.
- Withdrawal of rejected standing work reuses the controller's existing
  standing reconciliation rather than a new cancellation path: the app passes
  `declared_planners` (plain planner ids), so the engine stays blind to the
  policy and to why a proposal is missing.
- Policy logging is per decision, not change-gated: planner cadences are 5 s
  or more, so one line per candidate is small and gives every proposal a
  persisted evaluation under its `proposal_id`.

## Known issues

- A live FINITE mission is not withdrawn when its re-declared candidate is
  rejected (duplicates are rejected by the controller anyway); it runs to its
  own end or timeout.
- Tests that exercise Map Control allocation now need a spatial field: a
  patrol with no field offers nothing and is rejected.
- Logs round decision values, have no run id / sequence / schema version,
  stringify unknown objects (`default=str`), and do not persist the
  `StrategicContext` a policy decision read (Stage 2).
- `MissionController._preemption_cost` swallows executor exceptions silently
  (Stage 2).
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

## Next stage

Stage 2 -- make the decision trace causally reproducible: a layer-neutral
JSONL envelope (schema version, run id, sequence, iteration, exact game
time), a game-start record, persisted `StrategicContext` revisions referenced
by policy evaluations, spatial selection summaries, `mission.progressed` on
outcome changes, a logged `preemption_cost` fault, and joinable
Strategy -> candidate -> evaluation -> admission -> assignment -> progress
tests.

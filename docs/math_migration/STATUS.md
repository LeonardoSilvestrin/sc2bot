# Current status

Stabilization and auditability pass over the Strategy / StrategicIntent /
ControlObjective / Mission Policy integration, before any mathematical
migration. Rules: [PRINCIPLES.md](PRINCIPLES.md).

## Last completed commit

`refactor: complete control objective integration` (Stage 0), on top of the
user's WIP checkpoint `ffce62d strat agora é live`.

## Completed stages

- **Stage 0 -- control objective integration.** The unfinished consumer
  migration was already committed as `ffce62d` (18 files, +757/-106), so the
  worktree was clean; this stage finished it on top instead of rewriting it.
  - `ControlMatch(objective_id, alignment)` replaces the loose
    `control_objective` / `control_alignment` pair on `MissionSignals`. A match
    exists only at `alignment >= MINIMUM_CONTROL_ALIGNMENT` (0.5); an id never
    travels with a negligible alignment. Work serving no objective is valid.
  - Map Control's anchor evaluation (`evaluate_sample`, a pure function
    returning `MapControlCandidate`) is split into `local_value`, `caution`
    and `strategic_value`; `score = local - caution + strategic`. Strategy
    moves the anchor only through `strategic_value`.
  - `MissionSignals.opportunity` for the patrol is `local_value` over its best
    possible value: no risk, unknown space, intent or objective importance.
    Risk, information gain and the control match reach the policy as their
    own signals, priced once there.
  - Deterministic tie-breaks: objective pull ties go to the smaller id; a
    travel-origin distance tie goes by base position, not townhall order.
  - Docs no longer call Strategy or territory regions shadow/unconsumed.

## Tests and tooling

At Stage 0 (Windows, project `.venv`, Python 3.12):

- `pytest`: 789 passed.
- `ruff check bot tests`: clean (the six WIP errors are fixed).
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
  anchor away. The Mission Policy still prices importance x gap for the
  cross-mission decision.
- Contract 16 was already relaxed in `ffce62d` (`ConsumerTests`): macro and
  the mission engine never read territory; Strategy and behaviors may.

## Known issues

- Every non-fallback candidate gets priority >= 30 even at utility 0, above
  Standing (20); a test blesses it (Stage 1).
- `docs/contracts.md` "Mission kinds and priorities" and
  `docs/behavior/README.md` still list the pre-policy fixed priorities
  (Stage 1).
- Logs round decision values, have no run id / sequence / schema version,
  and stringify unknown objects (`default=str`); `mission.candidate` /
  `mission.ranked` are change-gated, so not every proposal has a persisted
  evaluation (Stage 2).
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

Stage 1 -- make mission viability explicit: `MissionPolicy` returns an
evaluation with raw utility, urgency floor, final utility, viability, reason
and priority only when viable; rejected candidates never reach
`MissionController`.

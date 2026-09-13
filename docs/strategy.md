# Strategy

`bot/strategy/` answers two questions:

> Given a normalized set of signals about the game, which strategic objective
> should dominate right now -- and what does that direction want, spelled out
> for every behavior that acts on it?

It decides a **direction** and the **world state it wants**, never an
execution. It says "PRESSURE", "harass is wanted at 0.9" and "the natural's
choke should be held", never "attack the enemy third with the main army".

Source: `bot/strategy/`.

**Live.** `StrategyRuntime` (`bot/app/strategy_runtime.py`) updates the
director every frame and, on each new snapshot, publishes a
`StrategicContext`: the `StrategicIntent` and the `ControlObjective`s.
Behavior planners read that context to choose targets; the Mission Policy
(`evaluate_mission`, run by `MissionRanker` in `bot/app/mission_ranking.py`)
evaluates every planner's candidates under it and proposes only the viable
ones. Macro does not read Strategy yet:
it still receives the legacy `MacroPosture`. Every weight below remains a
first guess until match logs show where it is wrong.

```text
AwarenessSnapshot --> awareness_adapter --> StrategyInputs
    |                                            |
    |                                    StrategicDirector
    |                                            |
    |                                    StrategySnapshot --> derive_intent
    |                                                               |
    +-----------------> derive_control_objectives <----- StrategicIntent
                                   |
                  StrategicContext (intent + ControlObjectives)
                        |                          |
               behavior planners            Mission Policy
           (targets, MissionSignals)   (evaluate_mission -> viable? priority)
```

The scoring, direction, intent and policy core (`model`, `config`,
`scoring`, `hysteresis`, `director`, `intent`, `mission_policy`, `posture`)
imports only itself, `bot.domain` (the legacy posture enum) and the standard
library, performs no I/O and knows no runtime, Ares, Attention, Awareness or
behavior. Only `awareness_adapter.py` and `spatial/policy.py` read Awareness.
Runtime coordination and logging live in `bot.app`. `bot.macro.strategy`
remains unrelated: it is macro's goal/opening vocabulary.

| Module | Holds |
| --- | --- |
| `model.py` | `StrategicObjective`, `StrategyInputs`, `ScoreContribution`, `ObjectiveAssessment`, `StrategySnapshot` |
| `config.py` | `StrategyConfig` and one small weights dataclass per objective |
| `scoring.py` | `score_stabilize` ... `score_pressure`, `assess_objectives` |
| `hysteresis.py` | `ObjectiveState`, `select_objective`, `decision_confidence` |
| `director.py` | `StrategicDirector`, the only stateful piece |
| `awareness_adapter.py` | the sole translation from `AwarenessSnapshot` to `StrategyInputs` |
| `intent.py` | `StrategicActivity`, `StrategicIntent`, `IntentConfig`, `derive_intent` |
| `spatial/` | `ControlObjective`, `SpatialStrategySnapshot`, `SpatialPolicyConfig`, `derive_control_objectives` |
| `context.py` | `StrategicContext`: what behaviors and the Mission Policy read |
| `mission_policy.py` | `MissionSignals`, `ControlMatch`, `ControlNeed`, `MissionPolicyConfig`, `MissionEvaluation`, `evaluate_mission`, `is_viable` |
| `posture.py` | temporary owner of the legacy `MacroPosture` policy macro still consumes |

## Inputs

`StrategyInputs` is a small immutable contract. Out-of-range and NaN values
raise; `StrategyInputs.clamped(...)` is the lenient constructor for a caller
whose arithmetic may drift past a bound (it still rejects NaN).

| Signal | Range | Meaning |
| --- | --- | --- |
| `military_edge` | -1 .. +1 | clearly behind .. even or unknown .. clearly ahead |
| `economic_edge` | -1 .. +1 | same, for the economy |
| `territory_edge` | -1 .. +1 | same, for the map we hold |
| `immediate_threat` | 0 .. 1 | enemy force acting on our position now |
| `base_exposure` | 0 .. 1 | how reachable our held bases are, whether or not anything is coming |
| `knowledge_confidence` | 0 .. 1 | how current and complete our knowledge of the enemy is |

An edge we cannot read is **0, never positive**. Low information does not
mean a weak enemy: low `knowledge_confidence` only ever lowers aggression.

## Objectives

Declaration order runs from the most defensive to the most aggressive. It is
also the tie-break order: on equal scores the more conservative objective
wins. There is no `FINISH`, no matchup-specific objective, no build order and
no target.

| Objective | When |
| --- | --- |
| `STABILIZE` | immediate risk of the position deteriorating: threat, exposure, military deficit |
| `RECOVER` | structurally behind (economy, army, territory) without an extreme crisis |
| `BUILD_ADVANTAGE` | stable enough to keep growing before taking risks; the common state and the conservative fallback |
| `TAKE_MAP_CONTROL` | a sufficient army and a safe home, with territory still left to take |
| `PRESSURE` | a reliable military edge, a safe home and good knowledge: take the initiative |

## Scoring

Each objective has its own independent score function. There is no decision
tree: which objective leads is only a comparison of scores. Scores are read in
[0, 1] and do not sum to 1.

```text
ahead(x)      = max(x, 0)          behind(x) = max(-x, 0)
home_security = (1 - immediate_threat) * (1 - base_exposure)

STABILIZE        = 0.70 threat + 0.30 exposure + 0.15 behind(military)

RECOVER          = 0.50 behind(economy) + 0.40 behind(military)
                 + 0.15 behind(territory) + 0.15 (1 - home_security)
                 - 0.30 threat

BUILD_ADVANTAGE  = 0.40 + 0.25 home_security - 0.40 threat
                 - 0.25 behind(military) - 0.30 ahead(military)
                 - 0.25 behind(economy) + 0.15 (1 - confidence)

TAKE_MAP_CONTROL = 0.45 support - 0.60 surplus * confidence - 0.30 behind(military)
                 + 0.15 home_security + 0.25 (1 - ahead(territory)) * support
                 + 0.10 confidence - 0.40 threat
    support = min(ahead(military) / 0.5, 1)    # a sufficient army, not an overwhelming one
    surplus = max(ahead(military) - 0.5, 0)    # the confident rest is PRESSURE's

PRESSURE         = 0.80 ahead(military) * confidence - 0.20 (1 - confidence)
                 + 0.20 home_security + 0.10 ahead(economy) + 0.10 ahead(territory)
                 - 0.50 threat

score = clamp(raw, 0, 1)
```

The shape of the ladder, as the military edge grows at a safe home:

- `BUILD_ADVANTAGE` has a flat baseline, so it leads whenever nothing else is
  clearly true -- including at cold start, where every input is 0.
- `TAKE_MAP_CONTROL` grows fastest up to a sufficient edge (0.5), and only
  where there is territory left to take.
- `PRESSURE` keeps growing past that, but only with the edge we are confident
  in. `TAKE_MAP_CONTROL` hands the confident surplus over to it.
- `immediate_threat` raises `STABILIZE` and lowers every ambition, so a crisis
  stabilizes even when we are ahead.

Every weight lives in `StrategyConfig` (`stabilize`, `recover`,
`build_advantage`, `take_map_control`, `pressure`). A weight is a magnitude:
whether a signal raises or lowers a score is fixed by the score function, so
retuning never flips an objective's meaning.

Reference readings with the default weights (`knowledge_confidence` 0.6 and
`base_exposure` 0.1 unless listed):

| Inputs | STAB | REC | BUILD | MAP | PRESS |
| --- | --- | --- | --- | --- | --- |
| cold start, everything 0 | 0.00 | 0.00 | **0.80** | 0.15 | 0.00 |
| even | 0.03 | 0.02 | **0.69** | 0.20 | 0.10 |
| threat 0.9, exposure 0.6 | **0.81** | 0.00 | 0.11 | 0.00 | 0.00 |
| military -0.5, economy -0.5, threat 0.1, exposure 0.2 | 0.21 | **0.46** | 0.35 | 0.00 | 0.01 |
| military 0.4, economy 0.1, threat 0.05 | 0.07 | 0.01 | 0.53 | **0.73** | 0.27 |
| military 0.8, economy 0.3, territory 0.4, exposure 0.05, confidence 0.9 | 0.02 | 0.01 | 0.41 | 0.67 | **0.82** |
| the same at confidence 0.2 | 0.02 | 0.01 | 0.52 | **0.73** | 0.23 |

Tests assert relations (which objective leads, which way a score moves), not
these numbers.

### Explainability

Every score carries its reasons. An `ObjectiveAssessment` holds the objective,
its clamped `score`, and a tuple of `ScoreContribution(signal, contribution)`
whose exact sum is `raw_score`. Each signal appears at most once. The derived
signals are `home_security` and, for `BUILD_ADVANTAGE`, `baseline`.

`PRESSURE` reports its confidence discount explicitly: `military_edge` is the
full edge, and `knowledge_confidence` is what incomplete knowledge takes back
from it (plus the flat uncertainty penalty):

```text
PRESSURE 0.82   (military 0.8, confidence 0.9)
  +0.64 military_edge
  -0.08 knowledge_confidence
  +0.19 home_security
  +0.03 economic_edge
  +0.04 territory_edge
  +0.00 immediate_threat
```

## Hysteresis

`select_objective` keeps the objective in force unless the best other
objective (the challenger) beats it clearly and lastingly:

```text
switch  iff  challenger_score >= current_score + switch_margin
        and  (time_in_objective >= minimum_dwell_seconds  or  emergency)

emergency  =  challenger is STABILIZE  and  immediate_threat >= emergency_threat
```

| `StrategyConfig` | Default | Role |
| --- | --- | --- |
| `update_interval_seconds` | 1.0 | recompute cadence; in between the previous snapshot is returned unchanged |
| `switch_margin` | 0.08 | lead a challenger needs over the objective in force |
| `minimum_dwell_seconds` | 20.0 | how long an objective is held before a normal switch |
| `emergency_threat` | 0.8 | threat at which `STABILIZE` skips the dwell (`None` disables it) |
| `initial_objective` | `BUILD_ADVANTAGE` | entered at the first update |
| `clear_lead` | 0.25 | lead that counts as full `confidence` |

- The emergency skips only the dwell, never the margin, and only towards
  `STABILIZE`. Leaving `STABILIZE` takes the normal dwell: wrongly cautious is
  cheap, wrongly greedy is not.
- There is no transition matrix: any objective may follow any other.

## Director and snapshot

`StrategicDirector.update(inputs, game_time)` scores every objective, applies
hysteresis and returns a `StrategySnapshot`. `game_time` must be finite and
never go backwards.

**Cold start.** The first update enters `initial_objective`
(`BUILD_ADVANTAGE`) at that `game_time`, so the direction is never undefined.
Only an emergency leaves it before the first dwell is over.

| `StrategySnapshot` | |
| --- | --- |
| `objective` | the objective in force, after hysteresis |
| `confidence` | `clamp((score(objective) - best other score) / clear_lead, 0, 1)`: 0 when tied, or when hysteresis holds the objective against a better score |
| `assessments` | every `ObjectiveAssessment`, in `StrategicObjective` order |
| `previous_objective` | what `objective` replaced; `None` before the first switch |
| `game_time` | when the snapshot was computed |
| `time_in_objective` | how long `objective` has been held at `game_time` |
| `inputs` | the `StrategyInputs` it was computed from |

`snapshot.leader` is the best-scoring objective this update, which can differ
from `objective` while hysteresis holds.

## Intent

`derive_intent` spells the objective out as a `StrategicIntent`: independent
0..1 preferences for `defense`, `map_control`, `harass` and `information`,
plus `risk_tolerance`. They are not shares of a whole. `IntentConfig` holds
one profile per objective; `held_share` (0.7) of the intent is the profile of
the objective in force and the rest the score-weighted mix of every
objective's profile, so a close challenger shades the intent before
hysteresis lets it take over. Before the first snapshot the neutral context
uses the `BUILD_ADVANTAGE` profile.

| Profile | defense | map_control | harass | information | risk_tolerance |
| --- | ---: | ---: | ---: | ---: | ---: |
| `STABILIZE` | 0.95 | 0.15 | 0.10 | 0.45 | 0.15 |
| `RECOVER` | 0.75 | 0.20 | 0.25 | 0.55 | 0.25 |
| `BUILD_ADVANTAGE` | 0.60 | 0.25 | 0.65 | 0.55 | 0.40 |
| `TAKE_MAP_CONTROL` | 0.50 | 0.85 | 0.50 | 0.80 | 0.50 |
| `PRESSURE` | 0.35 | 0.65 | 0.90 | 0.60 | 0.70 |

No behavior reads the objective itself: the direction is interpreted once,
here, the same way for everyone.

## Control objectives

`derive_control_objectives(intent, awareness)` (`spatial/policy.py`) says
where control is wanted. A `ControlObjective` names a base, region or
passage, how firmly Strategy wants it held (`desired_control`) and watched
(`desired_visibility`), its `importance`, and Awareness' reading of the place
when it was derived (`current_control`, `current_visibility`); `gap` is the
larger shortfall. It names no unit, count, formation or priority.

| Kind | One per | Activity | Importance |
| --- | --- | --- | --- |
| `BASE` | held base | `DEFENSE` | `intent.defense` x stake (main 1, expansion 0.9) x raised exposure x raised facing, + 0.3 x threat |
| `PASSAGE` | way into a held base's region, at most 3 per base | `DEFENSE` | the base's importance, x 0.35 for a link between two held bases, x raised facing |
| `REGION` | approach region one passage outside our own, at most 4 | `MAP_CONTROL` or `INFORMATION`, whichever value is larger | 0.9 x max(`intent.map_control` x ground access, `intent.information` x (1 - confidence)) |

`raised(floor, x) = floor + (1 - floor) * x`, with an exposure floor of 0.45
and a facing floor of 0.7. Objectives under importance 0.05 are dropped; the
rest are sorted by `(-importance, objective_id)`, and every snapshot is
complete -- an objective missing from it is no longer wanted. Importance
never reads how firmly we already hold a place, so our own army arriving does
not argue an objective away. Every number lives in `SpatialPolicyConfig`.

## Mission Policy

A behavior planner describes each concrete opportunity as `MissionSignals`,
in local terms only: `activity`, `opportunity`, `urgency`, `risk`,
`information_gain` (each 0..1) and an optional `control: ControlMatch`.
`evaluate_mission` is the one place those terms meet the intent. It returns a
`MissionEvaluation` holding every term below as it was computed:

```text
desirability = floor + (1 - floor) * intent[activity]
value        = value_share * desirability * (
                   opportunity_weight * opportunity
                 + information_weight * information_gain * intent.information
                 + control_weight     * alignment * importance * gap)
urgency      = urgency_weight * urgency
risk         = risk_weight * risk
               * (unavoidable + (1 - unavoidable) * (1 - risk_tolerance))
raw_utility  = value + urgency - risk
floor        = emergency_utility
               * clamp((urgency - emergency_urgency) / (1 - emergency_urgency))
utility      = clamp(max(raw_utility, floor), 0, 1)
viable       = utility > minimum_viable_utility                  (is_viable)
priority     = minimum_priority
               + round((maximum_priority - minimum_priority) * utility)   viable only
```

| `MissionPolicyConfig` | Default |
| --- | ---: |
| `opportunity_weight`, `information_weight`, `control_weight` | 0.55, 0.20, 0.25 |
| `desirability_floor`, `value_share` | 0.15, 0.85 |
| `urgency_weight` | 0.45 |
| `emergency_urgency`, `emergency_utility` | 0.5, 0.95 |
| `risk_weight`, `unavoidable_risk_share` | 0.40, 0.15 |
| `minimum_viable_utility` | 0.0 |
| `fallback_priority`, `minimum_priority`, `maximum_priority` | 20, 30, 100 |

**Viability.** A candidate is executable only when its final utility is
above `minimum_viable_utility`: at the default 0, when it is worth anything at
all. A rejected evaluation has no priority, and `MissionRanker` never turns it
into a proposal -- it is logged and goes no further, so it can neither be
admitted nor take a unit. The emergency floor is applied *before* the
predicate, so a genuine emergency stays viable even when risk makes its
ordinary raw utility negative. The fallback owner (`activity` `None`, the
standing army) is not weighed: it is always viable, at `fallback_priority`,
the explicit owner of whatever no viable mission takes.

| `reason` | When |
| --- | --- |
| `fallback_owner` | the standing army's fallback signals |
| `viable_positive_utility` | viable on its own raw utility |
| `viable_by_urgency_floor` | viable, the emergency floor above the raw utility |
| `rejected_negative_raw_utility` | not viable; risk outweighed everything |
| `rejected_utility_not_above_minimum` | not viable; nothing negative, but not enough |

**One price per factor.** A planner's `opportunity` must not already contain
risk, information, urgency, strategic desirability or an objective's
importance: the policy prices each of them once, from its own signal. A
behavior may weigh all of them to *choose* a target -- that is its own
decision -- but reports the chosen target's local value as opportunity (see
Map Control's anchor, [behavior/map-control.md](behavior/map-control.md)).

**Control matches.** `ControlMatch(objective_id, alignment)` exists only for
`alignment >= MINIMUM_CONTROL_ALIGNMENT` (0.5): the work is at least half as
direct as standing on the objective. A weaker association is not a match: it
carries no objective id and prices no control. Work serving no objective is
still ranked on every other term. The control term reads the objective's
importance and gap from the current context; a match to an objective the
context no longer holds prices nothing. Defense matches its base's objective
at alignment 1; Map Control matches the approach objective its anchor lies
near (a Gaussian over 1.5 grid steps).

## Context revisions and the record

`StrategyRuntime` derives a candidate `StrategicContext` from every new
snapshot but publishes it only when it is materially different -- another
intent or another set of control objectives, compared exactly -- under the
next `revision`. A revision therefore names one set of prescriptions; 0 is the
neutral context before Strategy has run.

Before the Mission Policy's first decision under a revision, the frame calls
`record_context()`, which writes `strategy.context` once for that revision:
the objective, leader and confidence, every assessment with its score
contributions, the six inputs, the intent and every control objective, at
machine precision. Each record is complete, so an objective absent from a
later record is no longer wanted. `mission.evaluated` cites the revision
(`context_revision`) instead of copying the context.

## Deliberately out of scope

Strategy decides direction and the world state it wants, not execution. It
has no:

- attack target, unit position or path (a `ControlObjective` names a place
  whose control is wanted, never where a unit stands);
- army allocation, squads, missions or unit counts;
- production recommendation or build order;
- map control percentage or territory model of its own;
- `FINISH` objective, matchup-specific strategy;
- rule engine, GOAP, MCTS, behavior tree or ML;
- logging or telemetry (the app owns those).

## Awareness -> Strategy adapter

`build_strategy_inputs` builds `StrategyInputs` from `AwarenessSnapshot`,
keeping the model/director unaware of Awareness. Current mappings are:

| Signal | Candidate source |
| --- | --- |
| `military_edge` | `2 * army.relative.advantage - 1` |
| `economic_edge` | `2 * economy.relative.advantage - 1` |
| `territory_edge` | mean sample `dominance`, discounted by local confidence |
| `immediate_threat` | `bases` security (`THREATENED`/`CRITICAL`) and `threat.near_own_base_enemy_combat_units` |
| `base_exposure` | `1 - ground_security` of the held bases' territory regions |
| `knowledge_confidence` | mean territory, army and economy confidence |

The app logs the first result, objective transitions and periodic samples as
`strategy.updated`. Gameplay reads the objective only through the intent and
the control objectives. Macro, the last legacy consumer, still receives
`MacroPosture`; its unchanged policy lives in Strategy (`posture.py`) and is
copied into the deprecated Awareness snapshot field only for compatibility.

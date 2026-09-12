# Strategy

`bot/strategy/` answers one question:

> Given a normalized set of signals about the game, which strategic objective
> should dominate right now?

It decides a **direction**, never an execution. It says "PRESSURE", never
"attack the enemy third with the main army".

**Shadow mode.** Strategy is a pure layer with no producer and no consumer
yet: nothing builds `StrategyInputs` from Awareness, and nothing in the bot
reads a `StrategySnapshot`. `tests/test_strategy_architecture.py`
(`ShadowModeTests`) fails if any `bot/` module outside `bot/strategy/`
imports it, so wiring a consumer is a deliberate change: delete that guard
when it happens. Every weight below is a first guess, left untuned until
shadow-mode logs show where it is wrong.

```text
Awareness
    |
[adapter, not built yet]
    v
StrategyInputs --> scoring --> hysteresis --> StrategySnapshot
                   \_______ StrategicDirector _______/
    |
[consumers, not built yet]
```

`bot.strategy` imports only itself and the standard library (`dataclasses`,
`enum`, `math`, `collections.abc`), performs no I/O and knows no runtime,
Ares, Attention, Awareness or behavior. It is fully testable with synthetic
inputs. `bot.macro.strategy` is unrelated: macro's goal/opening vocabulary.

| Module | Holds |
| --- | --- |
| `model.py` | `StrategicObjective`, `StrategyInputs`, `ScoreContribution`, `ObjectiveAssessment`, `StrategySnapshot` |
| `config.py` | `StrategyConfig` and one small weights dataclass per objective |
| `scoring.py` | `score_stabilize` ... `score_pressure`, `assess_objectives` |
| `hysteresis.py` | `ObjectiveState`, `select_objective`, `decision_confidence` |
| `director.py` | `StrategicDirector`, the only stateful piece |

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

## Deliberately out of scope

Strategy decides direction, not execution. It has no:

- target position, target base, attack target or coordinates;
- army allocation, squads, missions or unit counts;
- production recommendation, build order or macro posture;
- map control percentage or territory model of its own;
- `FINISH` objective, matchup-specific strategy;
- rule engine, GOAP, MCTS, behavior tree or ML;
- logging, telemetry or runtime integration;
- adapter from Awareness.

## Future integration: Awareness -> Strategy

A future adapter will build `StrategyInputs` from `AwarenessSnapshot`, keeping
`StrategyInputs` itself unaware of Awareness. Plausible first mappings, all
to be validated against shadow-mode logs:

| Signal | Candidate source |
| --- | --- |
| `military_edge` | `2 * army.relative.advantage - 1` |
| `economic_edge` | `2 * economy.relative.advantage - 1` |
| `territory_edge` | mean `dominance` of the territory regions, weighted by value |
| `immediate_threat` | `bases` security (`THREATENED`/`CRITICAL`) and `threat.near_own_base_enemy_combat_units` |
| `base_exposure` | `1 - ground_security` of the held bases' territory regions |
| `knowledge_confidence` | `territory.confidence` combined with the army/economy belief confidences |

Then, in order: run the director in shadow mode inside the frame lifecycle and
log snapshot changes; tune weights from those logs; only then let a first
consumer read the objective, deleting `ShadowModeTests`.

# Openings and builds

A build has two halves. The **opening** is a deterministic Ares build order in
`terran_builds.yml`, run by Ares' `BuildOrderRunner`. The **goal set** is what
the bot converges to afterwards, a `MacroGoalSet` in
`bot/macro/builds/<build>/plan.py`, pursued by
[`MacroPlanner`](macro-planner.md). Three builds exist; every game plays
`BattleMech`.

Source: `terran_builds.yml`, `config.yml`, `bot/app/opening.py`,
`bot/macro/builds/`, `bot/macro/strategy/openings.py`,
`bot/macro/strategy/reference_build.py`, `bot/behavior/strategy_intent.py`.

## Which opening plays

`terran_builds.yml`:

```yaml
UseData: false            # never persist opponent history: ladder-safe
BuildSelection: Cycle
BuildChoices:             # test_123, Protoss, Terran, Zerg, Random
  <key>:
    Cycle:
      - BattleMech        # every cycle is pinned to BattleMech
```

With `UseData: false`, Ares always resolves the cycle to `Cycle[0]`.
`OpeningSelector` ([app.md](../app.md#opening-selection)) re-picks uniformly
from the same cycle at `on_start`, before the runner takes a step, and posts
`[Build] <opening>` in chat. The cycle key is the opponent id when listed,
`test_123` while `config.yml` has `Debug: True` (it currently does), otherwise
the enemy race. Adding an opening back to a cycle is all it takes to roll
between them again.

## Handoff to macro

The YAML owns only the opening, but macro does not wait for it:

- While the runner is still stepping, `AresWorldObserver` prices the current
  and next step (capped at 600 minerals and 400 gas) into
  `EconomyFacts.protected_minerals/vespene`, and `EconomyController` withholds
  that before admitting anything. Macro only spends a genuine surplus.
- Supply depots and add-ons wait for `opening_completed`
  ([macro-planner.md](macro-planner.md#macroplannerproposeattention-awareness)).
- `MacroPlanner` adopts the opening's goal set the first tick the opening name
  is known, through `MACRO_PROFILES`:

| Opening | Goal set | Reference build |
| --- | --- | --- |
| `BattleMech` | `battle_mech()` | none |
| `BioThreeOneOne` | `bio_three_one_one()` | `bio_three_one_one_reference()` |
| `BansheeCloak` | `banshee_cloak()` | none |
| anything else | `bio_three_one_one()` | Bio reference |

- Once the runner reports `build_completed`, nothing is protected and macro
  owns production, expansions and composition.
- `BuildStrategicIntent` lets the Banshee raid run for `BansheeCloak` and
  `BattleMech` ([behavior/harass.md](../behavior/harass.md)). Neither the
  openings nor the goal sets scout: scouting is `IntelPlanner`'s alone.

All three openings share `AutoSupplyAtSupply: 30`, `PersistentWorker: false`
and `ShouldHandleGasSteal: true`, and start with the same Reaper expand:
depot and Barracks at the ramp, gas, Orbital, Reaper, expand.

## BattleMech (played)

### Opening

```text
14 supply @ ramp              20 supply @ ramp                 26 starporttechlab
16 barracks @ ramp            20 factory                       28 banshee
16 gas                        21 gas                           30 bansheecloak
 0 orbital                    22 addonswap factory barracksreactor   30 orbital
 0 reaper                     22 starport
19 expand                     22 hellion *4
19 barracksreactor
```

`ConstantWorkerProductionTill: 50`. The Barracks builds a Reactor while the
Factory goes down; `addonswap factory barracksreactor` (Ares' `AddonSwap`)
flies the Factory onto the Reactor and the Barracks to the Factory's old spot,
and the Factory makes four Hellions two at a time. A single Starport builds
its own Tech Lab for one Banshee and Cloaking Field, and the natural becomes
an Orbital.

### Goal set (`builds/battle_mech/plan.py`, doctrine `MECH`)

| Limits | |
| --- | --- |
| workers / townhalls | 70 / 4 |
| workers per townhall, refineries per townhall, max refineries | 22, 2, 8 |
| army supply target | 110 |

| Army member | Weight | Minimum | Cost | Desired at 110 supply |
| --- | ---: | ---: | --- | ---: |
| Hellion | 3 | 4 | 100m, 2 supply | 14 |
| Cyclone | 2 | 1 | 125m 50g, 3 supply | 10 |
| Siege Tank | 3 | 2 | 150m 125g, 3 supply | 14 |
| Banshee | 1 | 1 | 150m 100g, 3 supply | 5 |

(24 supply per composition cycle, 4.58 cycles; the bank-overflow bonus raises
the target by 8 supply per step.)

| Production | Min | Max | Growth | Milestone | Dynamic growth waits for |
| --- | ---: | ---: | --- | --- | --- |
| Barracks | 1 | 1 | -- | -- | -- |
| Factory | 1 | 5 | +1 at 900 gas/min, +1 per 450 more | 3 with the third townhall | 3 ready townhalls |
| Starport | 1 | 2 | -- | 2 with the third townhall | 3 ready townhalls |

| Add-on | Target total | Cost |
| --- | ---: | --- |
| Factory Tech Lab | 2 | 50m 25g |
| Starport Tech Lab | 2 | 50m 25g |

Structure timing is keyed on bases, not the clock: starting the third Command
Center raises the Factory floor to three and the Starport floor to two, and
the two new Factories and the second Starport take Tech Labs (the first
Factory keeps its Reactor). Bank- and income-driven growth above those floors
waits for the third to be **ready**, so gas saved for the expansion cannot
turn into premature Factories. No upgrades are declared.

## BioThreeOneOne (defined, not played)

### Opening

```text
14 supply @ ramp       20 supply @ ramp        23 barracks *2            27 starportreactor     32 marine *4
16 barracks @ ramp     20 barracksreactor      24 starport               28 engineeringbay      36 medivac *2
16 gas                 21 factory @ ramp       25 barrackstechlab *2     28 terraninfantryweaponslevel1
 0 orbital             21 gas                  26 stimpack               30 orbital
 0 reaper              22 marine *2            26 shieldwall
19 expand
```

`ConstantWorkerProductionTill: 55`. Converges on the common Bio 3-1-1: three
Barracks, one Factory, one Starport, Stim, Combat Shield, +1 Infantry Weapons
and two Medivacs.

### Goal set (`builds/bio_three_one_one/plan.py`, doctrine `BIO`)

Limits: 70 workers, 4 townhalls, 22 per townhall, 2 refineries per townhall
(8 max), army supply target 115.

| Army member | Weight | Minimum | Cost | Desired at 115 supply |
| --- | ---: | ---: | --- | ---: |
| Marine | 8 | 12 | 50m, 1 supply | 39 |
| Marauder | 3 | 4 | 100m 25g, 2 supply | 15 |
| Medivac (+2 priority) | 2 | 2 | 100m 100g, 2 supply | 10 |
| Siege Tank | 2 | 2 | 150m 125g, 3 supply | 10 |

| Production | Min | Max | Growth |
| --- | ---: | ---: | --- |
| Barracks | 3 | 8 | +1 at 1200 minerals/min, +1 per 500 more |
| Factory | 1 | 3 | +1 at 650 gas/min, +1 per 450 more |
| Starport | 1 | 3 | +1 at 800 gas/min, +1 per 500 more |

Add-ons: Barracks Tech Lab 2, Factory Tech Lab 1, Starport Reactor 1.
Declared upgrades (unused by macro): Stimpack, Combat Shield, Infantry
Weapons 1. Reference build floor: Barracks 1 at 0:41, 2 at 1:51, 3 at 2:17,
Factory at 4:34, Starport at 6:12.

## BansheeCloak (defined, not played)

### Opening

```text
14 supply @ ramp       20 supply @ ramp      23 starporttechlab *2    28 orbital
16 barracks @ ramp     20 factory @ ramp     24 banshee *2            30 barracksreactor
16 gas                 21 gas                26 marine *2             32 marine *2
 0 orbital             22 starport *2        27 bansheecloak          36 banshee
 0 reaper              22 marine             27 bansheespeed
19 expand
```

`ConstantWorkerProductionTill: 50`. The same Reaper expand, then a pivot at
the Factory into two Tech Lab Starports, two Banshees, Cloaking Field and
Hyperflight Rotors, with Marines spending the otherwise idle Barracks'
minerals, then a second Orbital, a Barracks Reactor and a third Banshee. The
opening only prepares tech and units; the Banshee raid casts cloak itself.

### Goal set (`builds/banshee_cloak/plan.py`, doctrine `BIO`)

Limits as Bio; army supply target 100.

| Army member | Weight | Minimum | Cost | Desired at 100 supply |
| --- | ---: | ---: | --- | ---: |
| Banshee | 3 | 3 | 150m 100g, 3 supply | 12 |
| Marine | 6 | 8 | 50m, 1 supply | 24 |
| Marauder | 2 | 2 | 100m 25g, 2 supply | 8 |
| Siege Tank | 2 | 2 | 150m 125g, 3 supply | 8 |

| Production | Min | Max | Growth |
| --- | ---: | ---: | --- |
| Barracks | 2 | 5 | +1 at 1000 minerals/min, +1 per 500 more |
| Starport | 2 | 3 | +1 at 500 gas/min, +1 per 400 more |
| Factory | 1 | 2 | -- |

Add-ons: Starport Tech Lab 2, Barracks Tech Lab 1, Factory Tech Lab 1.
Declared upgrades (unused by macro): Stimpack, Hyperflight Rotors.

## Doctrines (`composition/doctrine.py`)

A doctrine is production intent in three tiers. It bounds what a goal set may
buy and never reaches the mission system ([engine/capabilities.md](../engine/capabilities.md#composition-doctrine-botmacrocomposition)).

| Doctrine | Core | Support | Specialized | Used by |
| --- | --- | --- | --- | --- |
| `BIO` | Marine, Marauder, Siege Tank | Medivac, Viking | Banshee | `bio_three_one_one`, `banshee_cloak` |
| `MECH` | Hellion, Cyclone, Siege Tank | Viking, Thor | Banshee | `battle_mech` |

## Adding a build

1. Add the opening under `Builds:` in `terran_builds.yml` and put it in the
   cycles that should roll it.
2. Create `bot/macro/builds/<name>/plan.py` returning a `MacroGoalSet` within a
   doctrine (`tests/test_macro_architecture.py` requires the file for every
   registered profile).
3. Register it in `MACRO_PROFILES` (`bot/macro/strategy/openings.py`), with or
   without a reference build.
4. If a behavior depends on it (as the Banshee raid does), add the opening to
   `BuildStrategicIntent`.
5. Optionally give it a chat description in `_OPENING_ANNOUNCEMENTS`
   (`bot/app/opening.py`).
6. Document it here.

References:

- https://aressc2.github.io/ares-sc2/tutorials/build_runner.html
- https://github.com/AresSC2/ares-sc2/blob/main/examples/build_runner_examples/terran_builds.yml
- https://terrancraft.com/2020/01/21/tvp-standard-3-1-1-framework/

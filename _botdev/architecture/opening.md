# Openings

`terran_builds.yml` activates the Ares BuildOrderRunner with two openings,
both starting from the same Reaper expand:

- `BioThreeOneOne` converges on the common Bio 3-1-1 structure: three
  Barracks, one Factory, one Starport, Stim, Combat Shield, +1 Infantry
  Weapons, and two Medivacs.
- `BansheeCloak` pivots at the Factory into cloaked Banshee harass (below).

## Which opening plays

With `UseData: false` (deliberately, for ladder safety -- no opponent history
is ever written to disk), Ares' `DataManager.initialise()` always sets
`chosen_opening = build_cycle[0]` and never advances through the rest of a
race's `Cycle` list; `BuildSelection: Cycle` only actually cycles when
`UseData: true`. `BotRuntime` therefore re-rolls the opening itself in
`on_start`, before the runner has taken a step: `_choose_and_announce_opening`
picks uniformly at random from the same configured `Cycle` (the opponent id's
entry if there is one, otherwise the enemy race's), calls
`build_order_runner.switch_opening`, and announces the choice in game chat
(`Plan: Reaper expand into Bio 3-1-1.` or `Plan: Reaper expand into cloaked
Banshee harass.`). List order no longer decides anything: every race's cycle
lists both openings, so each plays about half the time.

When `config.yml` sets `Debug: True`, the lookup uses Ares' `TEST_OPPONENT_ID`
(`test_123`) instead, whose `Cycle` is `[BansheeCloak]` -- a way to test that
opener locally regardless of the roll. `config.yml` currently has
`Debug: True`, with a TODO to revert it, so every game plays `BansheeCloak`
until that is switched back.

## Handoff to macro

The YAML owns only the deterministic opening, but `MacroPlanner` does not wait
for it to finish. While the runner is still stepping,
`AresWorldObserver._protected_commitment_cost` prices the opening's next two
steps (capped at 600 minerals and 400 gas) into
`EconomyFacts.protected_minerals`/`protected_vespene`, and `EconomyController`
withholds that amount before admitting anything. Macro therefore only spends a
genuine surplus during the opening. The one thing it holds back entirely is
add-ons, which wait for `economy.opening_completed` because they contend for a
production slot the opening may still need, not just for money. Once the
runner reports `build_completed`, nothing is protected and `MacroPlanner` owns
production, expansions, and composition -- see
[macro-planner.md](macro-planner.md) for how it picks the right convergence
goals for whichever opening actually ran.

## BansheeCloak

`BansheeCloak` follows the identical Reaper-expand start -- the same first
seven steps as `BioThreeOneOne` (depot, Barracks, gas, Orbital, Reaper,
expand, depot) -- and then goes Factory, second gas, two Starports with Tech
Labs, two Banshees, Cloaking Field and Hyperflight Rotors, with Marines
spending the otherwise idle Barracks' minerals, then a second Orbital, a
Barracks Reactor and a third Banshee. The opening's only job is to have the tech and the units ready:
`BansheeHarassExecutor` casts `AbilityId.BEHAVIOR_CLOAKON_BANSHEE` through
`AresMissionCommands.use_ability` every step the raid is approaching,
infiltrating or striking (see
[harass-and-defense-planners.md](harass-and-defense-planners.md)), rather than
the opening pre-cloaking anything.

`bot.macro.strategy.openings.macro_config_for_opening` maps
`chosen_opening` to a matching `MacroPlannerConfig` (the `banshee_cloak()`
goal set in `bot/macro/strategy/profiles.py`, without a reference build) so
post-opening macro keeps producing Banshees instead of quietly reverting to
Bio's composition. `MacroPlanner(follow_opening=True)` performs this lookup
the first tick `economy.opening_name` is non-empty and locks it in for the
rest of the game. The Banshee harass behavior never asks for Banshees itself:
it reads how many exist, and producing them stays this macro profile's
decision. Its `StrategicIntent` only lets the raid run when the chosen opening
is `BansheeCloak`.

## Scouting

Scouting is deliberately absent from these build orders. The `IntelPlanner`
pilot owns the scout mission through a proposal, mission, lease, and traced
completion; the Ares build runner must not dispatch a second scout
independently. The scouting unit itself is a planner decision
(`IntelConfig.unit_types`, currently the Reaper both openings already
produce), not a build-order concern.

References:

- https://aressc2.github.io/ares-sc2/tutorials/build_runner.html
- https://github.com/AresSC2/ares-sc2/blob/main/examples/build_runner_examples/terran_builds.yml
- https://terrancraft.com/2020/01/21/tvp-standard-3-1-1-framework/

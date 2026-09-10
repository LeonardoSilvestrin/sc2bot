# Bio pilot opening

`terran_builds.yml` activates the Ares BuildOrderRunner. `BioThreeOneOne` is
`Cycle[0]` for every race, so it is the opening that actually plays out today
-- see "Cycle order and `UseData`" below for why a second entry does not
change that on its own.

It follows a Reaper expand and converges on the common Bio 3-1-1 structure:
three Barracks, one Factory, one Starport, Stim, Combat Shield, +1 Infantry
Weapons, and two Medivacs.

The YAML is deliberately limited to the opening. Once
`build_order_runner.build_completed` is true, `MacroPlanner` owns production,
expansions, upgrades, and composition -- see
[macro-planner.md](macro-planner.md) for how it picks the right convergence
goals for whichever opening actually ran.

## BansheeCloak opening

A second opening, `BansheeCloak`, follows the identical Reaper-expand start
(same first eight steps as `BioThreeOneOne`) and then pivots at the Factory:
Starport, a Starport Tech Lab, two Banshees, and the Banshee Cloaking Field
research, instead of Bio's second Barracks/Stim/Shield tech. `AresMissionCommands
.use_ability` casts `AbilityId.BEHAVIOR_CLOAKON_BANSHEE` every step the
harasser is on a live `AIR_HARASS` mission (see
[harass-and-defense-planners.md](harass-and-defense-planners.md)) rather than
the opening itself pre-cloaking anything; the opening's only job is to have
the tech and the units ready.

`bot.behavior.macro.opening_macro_profiles.macro_config_for_opening` maps
`chosen_opening` to a matching `MacroGoalSet` (`banshee_cloak()` in
`bot/behavior/macro/strategy_goal_profiles.py`)
so post-opening macro keeps producing Banshees instead of quietly reverting
to Bio's composition. `BotRuntime._resolve_macro_profile` performs this
lookup once `build_order_runner.chosen_opening` is non-empty and locks it in
for the rest of the game.

## Cycle order and `UseData`

`UseData: false` (deliberately, for ladder safety -- no opponent history is
ever written to disk) means Ares's `DataManager.initialise()` always sets
`chosen_opening = build_cycle[0]` and never advances through the rest of a
race's `Cycle` list; `BuildSelection: Cycle` only actually cycles when
`UseData: true`. Concretely: appending `BansheeCloak` to a race's `Cycle`
makes it a documented, available option, but a real ladder game still plays
`BioThreeOneOne` until someone reorders the list, turns `UseData` on, or
selects it explicitly for that opponent id.

For local testing regardless of ordering, `BuildChoices.test_123` (active
only when `config.yml` sets `Debug: True`) is dedicated to exactly this --
its `Cycle` is `[BansheeCloak]`.

Scouting is deliberately absent from this build order. The `IntelPlanner` pilot
owns the scout mission through a proposal, mission, lease, and traced
completion; the Ares build runner must not dispatch a second scout
independently. The scouting unit itself is a planner decision
(`IntelConfig.unit_types`, currently the Reaper this build already
produces), not a build-order concern.

References:

- https://aressc2.github.io/ares-sc2/tutorials/build_runner.html
- https://github.com/AresSC2/ares-sc2/blob/main/examples/build_runner_examples/terran_builds.yml
- https://terrancraft.com/2020/01/21/tvp-standard-3-1-1-framework/

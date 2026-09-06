# Bio pilot opening

`terran_builds.yml` activates the Ares BuildOrderRunner. The initial opening is
`BioThreeOneOne`, selected for every opponent race while matchup-specific builds
do not yet exist.

It follows a Reaper expand and converges on the common Bio 3-1-1 structure:
three Barracks, one Factory, one Starport, Stim, Combat Shield, +1 Infantry
Weapons, and two Medivacs.

The YAML is deliberately limited to the opening. Once
`build_order_runner.build_completed` is true, a future dynamic Bio macro module
must own production, expansions, upgrades, and composition.

Scouting is deliberately absent from this build order. The `IntelPlanner` pilot
owns the scout mission through a proposal, mission, lease, and traced
completion; the Ares build runner must not dispatch a second scout
independently. The scouting unit itself is a planner decision
(`IntelPlannerConfig.unit_types`, currently the Reaper this build already
produces), not a build-order concern.

References:

- https://aressc2.github.io/ares-sc2/tutorials/build_runner.html
- https://github.com/AresSC2/ares-sc2/blob/main/examples/build_runner_examples/terran_builds.yml
- https://terrancraft.com/2020/01/21/tvp-standard-3-1-1-framework/

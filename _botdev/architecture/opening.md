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

References:

- https://aressc2.github.io/ares-sc2/tutorials/build_runner.html
- https://github.com/AresSC2/ares-sc2/blob/main/examples/build_runner_examples/terran_builds.yml
- https://terrancraft.com/2020/01/21/tvp-standard-3-1-1-framework/

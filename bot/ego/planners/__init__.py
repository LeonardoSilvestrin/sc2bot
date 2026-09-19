"""PLANNERS: what should be done.

Each planner reads Attention, Awareness and Strategy, computes its own
priority from its local signals, modulated directly by `StrategyState`, and
hands complete plans to the Body. Four groups, one package each:

- `military` asks the Engine for army units: a `Proposal` with a task, a target, a
  priority and the units it requires, never naming a unit -- the Engine
  decides who gets each proposal, and the Body's behaviors how it is carried
  out. `offense` (the main attack) and `defense` (one area defense per threat
  incident) govern missions: the planner decides which operations to open and
  when to ask one to end, as Strategy's policy allows, and each mission carries
  one operation and makes its proposals.
  `map_control` takes what no one else needs, chooses where it stands and
  proposes directly.
- `intel` is cross-cutting: it can ask the Engine for a scout, order scans and
  maintain information structures through one `IntelPlan`.
- `economy` asks for no unit: what Ares' macro behaviors should buy.
- `control` asks for no unit either: direct control of existing structures
  (`structure_control`).

A planner with missions is a package with `planner.py` and one module per kind
of mission in `missions/`; what every mission shares is `bot.ego.missions`.
The contracts between the planners and the Body are in `contracts`.
"""

from .contracts import (
    Command,
    CompositionPlan,
    CounterAdaptation,
    DetectionPlan,
    Domain,
    EconomyPlan,
    IntelPlan,
    Proposal,
    SensorTowerPlan,
    SensorTowerSite,
    StructurePlan,
    SurvivalComposition,
)

__all__ = [
    "Command",
    "CompositionPlan",
    "CounterAdaptation",
    "DetectionPlan",
    "Domain",
    "EconomyPlan",
    "IntelPlan",
    "Proposal",
    "SensorTowerPlan",
    "SensorTowerSite",
    "StructurePlan",
    "SurvivalComposition",
]

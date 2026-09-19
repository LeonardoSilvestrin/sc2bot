"""Economy: what the bot spends its resources on after the opening.

A resource planner: it asks for no unit, only for what Ares' macro behaviors
should buy.

- `planner.plan`: the planner. Joins the policies and the chosen style into
  the `EconomyPlan` the Body's economy behavior runs.
- `policies.investment`: how much -- workers, bases, gas, production ceiling,
  and when the macro plan takes over from the opening.
- `policies.composition`: what now -- `CompositionPolicy` reweights the style's
  composition by what each unit is worth against the enemy army Awareness
  believes in.
- `knowledge.styles`: what -- the army styles, with their opening,
  composition, upgrades and add-ons, and the draw among them.
- `knowledge.counter_catalog`: the ordered responses to each enemy unit type
  (`knowledge/counters/*.yml`) and what each response can hit.
"""

from .knowledge.counter_catalog import CounterCatalog
from .knowledge.styles import ArmyStyle
from .planner import plan
from .policies.composition import CompositionConfig, CompositionPolicy
from .policies.investment import InvestmentConfig

__all__ = [
    "ArmyStyle",
    "CompositionConfig",
    "CompositionPolicy",
    "CounterCatalog",
    "InvestmentConfig",
    "plan",
]

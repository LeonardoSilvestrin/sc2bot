"""Economy: what the bot spends its resources on after the opening.

A resource planner: it asks for no unit, only for what Ares' macro behaviors
should buy. Three questions, one module each:

- `investment`: how much -- workers, bases, gas, production ceiling, and when
  the macro plan takes over from the opening.
- `styles`: what -- the army style chosen for the game, with its composition,
  upgrades and add-ons.
- `composition`: what now -- the style's composition reweighted by what each
  unit is worth against the enemy army Awareness believes in.

`planner.plan` joins them into the `EconomyPlan` the Body's economy behavior
runs.
"""

from . import composition, investment, styles
from .composition import CompositionConfig, CompositionPlanner
from .counter_catalog import CounterCatalog
from .investment import InvestmentConfig
from .planner import plan
from .styles import ArmyStyle

__all__ = [
    "ArmyStyle",
    "CompositionConfig",
    "CompositionPlanner",
    "CounterCatalog",
    "InvestmentConfig",
    "composition",
    "investment",
    "plan",
    "styles",
]

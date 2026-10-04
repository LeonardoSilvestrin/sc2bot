"""Economy: what the bot spends its resources on after the opening.

Beside the planners, not one of them: the planners decide what the units and
structures we have do, the economy decides what we buy. It asks for no unit,
only for what Ares' macro behaviors should buy.

- `contracts`: the `EconomyPlan` it hands the Body, and the `CompositionPlan`
  explaining its army.
- `planner.plan`: the planner. Joins the policies and the chosen style into
  the `EconomyPlan` the Body's economy behavior runs.
- `policies.investment`: how much -- workers, bases, gas, production ceiling,
  and when the macro plan takes over from the opening.
- `policies.composition`: what now -- `CompositionPolicy` chooses the mix
  worth most against the enemy army believed in, with the style as its prior.
- `knowledge.styles`: what -- the army styles, with their opening,
  composition, upgrades and add-ons, and the draw among them.
- `knowledge.combat`: how hard each unit type hits each other one and how much
  it takes (`knowledge/combat.yml`, refreshed from the client), and what each
  race's army is believed to be made of before any of it is seen.
"""

from .contracts import CompositionPlan, EconomyPlan, EnemyShare, SurvivalComposition
from .knowledge.combat import CombatModel
from .knowledge.styles import ArmyStyle
from .planner import plan
from .policies.composition import CompositionConfig, CompositionPolicy
from .policies.investment import InvestmentConfig

__all__ = [
    "ArmyStyle",
    "CombatModel",
    "CompositionConfig",
    "CompositionPlan",
    "CompositionPolicy",
    "EconomyPlan",
    "EnemyShare",
    "InvestmentConfig",
    "SurvivalComposition",
    "plan",
]

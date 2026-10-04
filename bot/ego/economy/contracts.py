"""CONTRACTS: what the economy hands the Body.

- `EconomyPlan`: what Ares' macro behaviors should buy.
- `CompositionPlan`, with its `EnemyShare` and `SurvivalComposition`: how the
  army the plan buys was chosen.
"""

from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId


@dataclass(frozen=True, slots=True)
class EnemyShare:
    """One enemy unit type as the composition policy believes in it."""

    # Canonical: a Siege Tank sieged or not is a Siege Tank.
    type_id: UnitTypeId
    # Power seen alive and not seen die, remembered.
    seen: float
    # Believed share of the enemy army's power.
    share: float
    # Our unit types by the share of our strength against it they make up.
    answers: tuple[tuple[UnitTypeId, float], ...] = ()
    # Power the enemy was seen to build of it, dead or alive, remembered.
    produced: float = 0.0


@dataclass(frozen=True, slots=True)
class SurvivalComposition:
    incident_id: str
    # Types added to the normal target so freeflow can use ready capacity.
    added: tuple[tuple[UnitTypeId, str], ...]


@dataclass(frozen=True, slots=True)
class CompositionPlan:
    style: str
    baseline: tuple[tuple[UnitTypeId, float, int], ...]
    enemy: tuple[EnemyShare, ...]
    # Enemy army power seen, and believed in (the observer's mean plus margin).
    seen_power: float
    believed_power: float
    # How much of the mix is the style's doctrine rather than the enemy:
    # doctrine_power / (produced_power + doctrine_power).
    doctrine: float
    # (unit type, share of the army's resources, availability): how soon its
    # tech lets it be trained, 1 when it can be now.
    mix: tuple[tuple[UnitTypeId, float, float], ...]
    # Enemy types seen that the combat model does not know, with their power.
    unmodeled: tuple[tuple[UnitTypeId, float], ...]
    survival: SurvivalComposition | None
    # Count proportions consumed by Ares.
    units: tuple[tuple[UnitTypeId, float, int], ...]
    tech_ready: tuple[UnitTypeId, ...]
    reason: str
    # Enemy army power seen built, dead or alive: the evidence of what the
    # enemy army is made of.
    produced_power: float = 0.0


@dataclass(frozen=True, slots=True)
class EconomyPlan:
    # False while Ares' build runner still plays the opening.
    active: bool
    workers: int
    gas: int
    bases: int
    expand: bool
    # Spend on army regardless of the composition's proportions.
    freeflow: bool
    # (unit type, proportion, priority): lower priority numbers build first.
    composition: tuple[tuple[UnitTypeId, float, int], ...]
    reason: str
    # The values the plan was computed from.
    inputs: tuple[tuple[str, float], ...] = ()
    # Upgrades to research, in order; the tech they need is built on the way.
    upgrades: tuple[UpgradeId, ...] = ()
    # Turn idle Command Centers into Orbital Commands.
    orbitals: bool = False
    # Orbital Commands spend their energy on MULEs.
    mules: bool = False
    # Stop Ares' build runner: the opening is over from this frame on.
    interrupt_opening: bool = False
    # The most structures of one production type (Barracks, Factory, Starport)
    # Ares may build; how many it builds within that is its income rule.
    max_production: int = 12
    # Put an add-on on an idle `addons_on` with none: a Reactor trains two
    # units at a time, a Tech Lab what needs one.
    addons: bool = False
    # The production structure that takes those add-ons.
    addons_on: UnitTypeId = UnitTypeId.BARRACKS
    # The share of those structures that should carry a Reactor; the rest take
    # Tech Labs.
    reactor_share: float = 1.0
    # The army style the composition and the upgrades come from.
    army: str = "bio"
    # Explanation of how the final composition was obtained.
    composition_plan: CompositionPlan | None = None

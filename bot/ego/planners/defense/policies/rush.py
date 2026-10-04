"""How much the game looks like a rush, and where a Bunker answers one.

A rush is an attack that comes before the army can answer it in the open. Two
things say one is on: the opening read promised it (`aggression` or `proxy`,
worth what its `confidence` says), or a base is pressed now (its remembered
threat). Either is enough, so they combine as independent evidence:

    rush = early_game * (1 - (1 - expected) * (1 - present))

Both only count early, and how much of the early game is left is Awareness'
belief (`early_game`), not a clock of this rule: once it is over an attack is
a timing the army answers, never a rush. Nothing here has memory of its own:
the opening read keeps what was observed and fades with its confidence, the
base threat fades with Awareness' `threat_memory`.

The Bunker goes where the rush will hit: in front of the natural once a
townhall stands there (on the spot Ares solved for it), else at the top of the
main ramp.
"""

from __future__ import annotations

from dataclasses import dataclass

from sc2.position import Point2

from bot.attention import AttentionState, BaseView
from bot.awareness import AwarenessState
from bot.ego.planners import BunkerSite

# A townhall this close to the natural stands on it.
_ON_SITE = 3.0
# How far in front of the natural a Bunker spot Ares solved may be.
_NATURAL_REACH = 15.0


@dataclass(frozen=True, slots=True)
class RushConfig:
    # A rush defense opens at this reading ...
    open_at: float = 0.5
    # ... and is over below this one, once no attacker presses its base.
    close_at: float = 0.15

    def __post_init__(self) -> None:
        if not 0.0 <= self.close_at < self.open_at <= 1.0:
            raise ValueError("expected 0 <= close_at < open_at <= 1")


@dataclass(frozen=True, slots=True)
class RushReading:
    # The rush reading, in [0, 1].
    level: float = 0.0
    # What the opening read promised: max(aggression, proxy) * confidence.
    expected: float = 0.0
    # The most any base is remembered threatened.
    present: float = 0.0
    # How much of the early game is left (Awareness' `early_game`).
    early_game: float = 0.0

    @property
    def inputs(self) -> tuple[tuple[str, float], ...]:
        return (
            ("rush", self.level),
            ("rush_expected", self.expected),
            ("rush_present", self.present),
            ("early_game", self.early_game),
        )


def read_rush(awareness: AwarenessState) -> RushReading:
    opening = awareness.opening
    expected = max(opening.aggression, opening.proxy) * opening.confidence
    present = max((base.recent_threat for base in awareness.bases), default=0.0)
    early = awareness.early_game
    level = early * (1.0 - (1.0 - expected) * (1.0 - present))
    return RushReading(level=level, expected=expected, present=present, early_game=early)


def bunker_site(attention: AttentionState) -> BunkerSite | None:
    """Where a rush is held: the natural once a townhall stands there, else
    the main; None without either."""

    map_view = attention.map
    natural = map_view.own_natural
    if natural is not None:
        base = _base_at(attention.bases, natural)
        if base is not None:
            spots = [
                spot
                for spot in map_view.bunker_sites
                if spot.distance_to(natural) <= _NATURAL_REACH
            ]
            near = min(
                spots, key=lambda spot: (spot.distance_to(natural), spot.x, spot.y), default=natural
            )
            return BunkerSite(site_id=base.base_id, base=natural, near=near)
    main = next((base for base in attention.bases if base.is_main), None)
    if main is None:
        return None
    return BunkerSite(site_id=main.base_id, base=map_view.own_start, near=map_view.main_ramp)


def _base_at(bases: tuple[BaseView, ...], point: Point2) -> BaseView | None:
    return next((base for base in bases if base.position.distance_to(point) <= _ON_SITE), None)

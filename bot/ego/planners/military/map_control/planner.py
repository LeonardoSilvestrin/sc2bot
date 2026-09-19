"""MapControlPlanner: where the army no operation needs stands.

Always proposed, always last -- below Defense and the offense: it asks for
every free army unit and holds them at its anchor. It is no strategic
reserve: it gets whatever the planners above left. No operation of its own,
so no missions.

The anchor is also where the offense assembles and falls back to: the frame
hands it to the `OffensePlanner` as the rally, and no planner calls another.

Where the anchor is, first match wins:

- `threatened_base`: STABILIZE with a threatened base -- the most threatened
  base, as the army's place is at home.
- `passage`: the passage that best keeps the enemy start from our bases, held
  a little on our side of it (`anchor`). The held passage is kept until
  another one scores `switch_margin` more; the candidates only change when a
  base is taken or lost.
- `legacy`: in front of the forward base, `rally_forward` toward the enemy
  start, or the main ramp while the main is the only base -- whenever no
  passage separates a base of ours from the enemy start or its anchor has no
  place on the lattice (`fallback` says which).

Its proposal keeps the id and owner `core_army`, its name before the renames:
the logs, the viewer and every bench so far know it by that name.
"""

from __future__ import annotations

from dataclasses import dataclass

from sc2.position import Point2

from bot.attention import AttentionState, MapView
from bot.awareness import AwarenessState
from bot.ego.planners import Command, Proposal
from bot.ego.strategy import Objective, StrategyState

from .anchor import PassageCandidate, anchor_of, candidates

OWNER = "core_army"
MAP_CONTROL_PRIORITY = -1.0
# Absorbs float noise so a challenger exactly `switch_margin` ahead counts.
_TOLERANCE = 1e-9

THREATENED_BASE = "threatened_base"
PASSAGE = "passage"
LEGACY = "legacy"


@dataclass(frozen=True, slots=True)
class MapControlConfig:
    # How far in front of the forward base the legacy anchor holds.
    rally_forward: float = 6.0
    # The score of a passage (`anchor`): protected + quality - overextension.
    base_value: float = 1.0
    quality_weight: float = 0.25
    width_scale: float = 6.0
    # How far a passage may be from a base it protects, as a share of the
    # distance between the starts, and still protect 1/e of it.
    reach_share: float = 0.5
    # How far on our side of the passage the army stands.
    setback: float = 4.0
    # A challenger must outscore the held passage by this much.
    switch_margin: float = 0.25

    def __post_init__(self) -> None:
        for name in ("rally_forward", "quality_weight", "setback"):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must not be negative")
        for name in ("base_value", "width_scale", "reach_share"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if self.switch_margin < 0.0:
            raise ValueError("switch_margin must not be negative")


@dataclass(frozen=True, slots=True)
class MapControlPlan:
    # Where the free army holds, and where the offense assembles.
    anchor: Point2
    # threatened_base, passage or legacy.
    source: str
    reason: str
    # The passage held and the region the army stands in; None unless the
    # anchor is the passage's.
    passage: PassageCandidate | None
    # Why no passage placed the anchor: no_separating_passage or
    # anchor_unresolved; None otherwise, and while a threatened base is held.
    fallback: str | None
    # Every passage that separates a base of ours from the enemy start, best first.
    candidates: tuple[PassageCandidate, ...]
    proposals: tuple[Proposal, ...]


class MapControlPlanner:
    def __init__(self, config: MapControlConfig | None = None) -> None:
        self.config = config or MapControlConfig()
        # The passage held, kept against challengers inside `switch_margin`.
        self._held: str | None = None
        # The candidates of the last map and set of bases, and each one's anchor.
        self._map: MapView | None = None
        self._bases: tuple[str, ...] | None = None
        self._candidates: tuple[PassageCandidate, ...] = ()
        self._anchors: dict[str, Point2 | None] = {}

    def plan(
        self, attention: AttentionState, awareness: AwarenessState, strategy: StrategyState
    ) -> MapControlPlan:
        found = self._evaluate(attention)
        passage = self._select(found)
        anchor = None if passage is None else self._anchor(attention.map, passage)
        fallback = (
            "no_separating_passage"
            if passage is None
            else "anchor_unresolved"
            if anchor is None
            else None
        )
        threatened = awareness.most_threatened
        objective = strategy.objective
        if objective is Objective.STABILIZE and threatened is not None:
            source, anchor, passage, fallback = THREATENED_BASE, threatened.position, None, None
        elif anchor is not None:
            source = PASSAGE
        else:
            source, anchor, passage = LEGACY, self._legacy(attention), None
        reason = f"hold_{'passage' if source == PASSAGE else 'rally'}_{objective.value.lower()}"
        inputs: tuple[tuple[str, float], ...] = (
            ("risk", strategy.risk),
            ("danger", awareness.danger),
        )
        if passage is not None:
            inputs += (
                ("protected", passage.protected),
                ("quality", passage.quality),
                ("overextension", passage.overextension),
                ("score", passage.score),
            )
        return MapControlPlan(
            anchor=anchor,
            source=source,
            reason=reason,
            passage=passage,
            fallback=fallback,
            candidates=found,
            proposals=(
                Proposal(
                    proposal_id=OWNER,
                    owner=OWNER,
                    priority=MAP_CONTROL_PRIORITY,
                    command=Command.HOLD,
                    target=anchor,
                    reason=reason,
                    inputs=inputs,
                ),
            ),
        )

    def _evaluate(self, attention: AttentionState) -> tuple[PassageCandidate, ...]:
        """The candidates, scored again only when the map or our bases change."""

        bases = tuple(base.base_id for base in attention.bases)
        if attention.map is not self._map or bases != self._bases:
            self._map, self._bases = attention.map, bases
            self._candidates = candidates(attention.map, attention.bases, self.config)
            self._anchors = {}
        return self._candidates

    def _select(self, found: tuple[PassageCandidate, ...]) -> PassageCandidate | None:
        if not found:
            self._held = None
            return None
        best = found[0]
        held = next((item for item in found if item.passage_id == self._held), None)
        if held is not None and best.score < held.score + self.config.switch_margin - _TOLERANCE:
            return held
        self._held = best.passage_id
        return best

    def _anchor(self, map_view: MapView, passage: PassageCandidate) -> Point2 | None:
        if passage.passage_id not in self._anchors:
            self._anchors[passage.passage_id] = anchor_of(map_view, passage, self.config.setback)
        return self._anchors[passage.passage_id]

    def _legacy(self, attention: AttentionState) -> Point2:
        map_view = attention.map
        front = max(
            attention.bases,
            key=lambda base: (base.position.distance_to(map_view.own_start), base.base_id),
            default=None,
        )
        if front is None or front.is_main:
            return map_view.main_ramp
        if front.position.distance_to(map_view.enemy_start) <= self.config.rally_forward:
            return front.position
        return front.position.towards(map_view.enemy_start, self.config.rally_forward)

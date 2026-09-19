"""MapControlPlanner: where the army no operation needs stands.

Always proposed, always last -- below Defense and the offense: it asks for
every free army unit and holds them at its anchor. It is no strategic
reserve: it gets whatever the planners above left. No operation of its own,
so no missions.

The anchor is where the uncommitted army reacts from and stages for the next
operation: the frame hands it to the `OffensePlanner` as the rally, where the
offense assembles and falls back to, and no planner calls another.

Where the anchor is, first match wins:

- `threatened_base`: STABILIZE with a threatened base -- the most threatened
  base, as the army's place is at home.
- the policy of `policy`:
  - `staging` (`staging`): the lattice point that best answers every base of
    ours, a little in front of them, on a choke that guards them if one is at
    hand, away from the enemy's influence; kept until another outscores it by
    `staging_margin`.
  - `passage` (`anchor`): the passage that best keeps the enemy start from our
    bases, held a little on our side of it; kept until another scores
    `switch_margin` more.
  Both are evaluated every frame, and the one not in `policy` is only logged
  beside the anchor, for comparison.
- `legacy`: in front of the forward base, `rally_forward` toward the enemy
  start, or the main ramp while the main is the only base -- whenever the
  policy places no anchor (`fallback` says why).

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
from .staging import StagingPlan, StagingPolicy

OWNER = "core_army"
MAP_CONTROL_PRIORITY = -1.0
# Absorbs float noise so a challenger exactly `switch_margin` ahead counts.
_TOLERANCE = 1e-9

THREATENED_BASE = "threatened_base"
STAGING = "staging"
PASSAGE = "passage"
LEGACY = "legacy"
POLICIES = (STAGING, PASSAGE)


@dataclass(frozen=True, slots=True)
class MapControlConfig:
    # The policy that places the anchor; the other is logged beside it.
    policy: str = STAGING
    # How far in front of the forward base the legacy anchor holds.
    rally_forward: float = 6.0
    # The staging score (`staging`): -reaction + choke - exposure.
    # How much standing in front of a base, on the enemy's way to it, shortens
    # the response to it while building an advantage; none while stabilizing.
    advance: float = 0.7
    choke_weight: float = 0.15
    threat_weight: float = 0.3
    control_weight: float = 0.2
    # A challenger must outscore the held point by this much, in shares of the
    # distance between the starts, while our bases and the objective hold.
    staging_margin: float = 0.04
    # How many regions' best candidates are logged.
    top_candidates: int = 5
    # The score of a passage (`anchor`): protected + quality - overextension.
    base_value: float = 1.0
    quality_weight: float = 0.25
    # How narrow a choke is, for both policies: exp(-width / width_scale).
    width_scale: float = 6.0
    # How far a passage may be from a base it protects, as a share of the
    # distance between the starts, and still protect 1/e of it.
    reach_share: float = 0.5
    # How far on our side of a passage the army stands, for both policies.
    setback: float = 4.0
    # A challenger must outscore the held passage by this much.
    switch_margin: float = 0.25

    def __post_init__(self) -> None:
        if self.policy not in POLICIES:
            raise ValueError(f"policy must be one of {POLICIES}")
        if not 0.0 <= self.advance <= 1.0:
            raise ValueError("advance must be between 0 and 1")
        for name in (
            "rally_forward",
            "choke_weight",
            "threat_weight",
            "control_weight",
            "quality_weight",
            "setback",
        ):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must not be negative")
        for name in ("base_value", "width_scale", "reach_share"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if min(self.switch_margin, self.staging_margin) < 0.0:
            raise ValueError("switch_margin and staging_margin must not be negative")
        if self.top_candidates < 1:
            raise ValueError("top_candidates must be at least 1")


@dataclass(frozen=True, slots=True)
class PassagePlan:
    """What the single-passage policy holds this frame."""

    # The passage held; None without one.
    held: PassageCandidate | None
    # Where the army would stand to hold it; None without a lattice point.
    anchor: Point2 | None
    # no_separating_passage or anchor_unresolved; None with an anchor.
    fallback: str | None
    # Every passage that separates a base of ours from the enemy start, best first.
    candidates: tuple[PassageCandidate, ...]


@dataclass(frozen=True, slots=True)
class MapControlPlan:
    # Where the free army holds, and where the offense assembles.
    anchor: Point2
    # threatened_base, staging, passage or legacy.
    source: str
    reason: str
    # The policy that places the anchor: staging or passage.
    policy: str
    # Why the policy placed no anchor -- no_candidates or no_enemy_route
    # (staging), no_separating_passage or anchor_unresolved (passage); None
    # otherwise, and while a threatened base is held.
    fallback: str | None
    # Each policy's choice this frame, whether it places the anchor or not;
    # staging is None without candidates.
    staging: StagingPlan | None
    passage: PassagePlan
    proposals: tuple[Proposal, ...]

    @property
    def held_passage(self) -> str | None:
        """The passage the anchor holds, if it holds one."""

        if self.source == STAGING and self.staging is not None:
            return self.staging.selected.passage_id
        if self.source == PASSAGE and self.passage.held is not None:
            return self.passage.held.passage_id
        return None

    @property
    def region(self) -> str | None:
        """The region the anchor stands in, when a policy placed it."""

        if self.source == STAGING and self.staging is not None:
            return self.staging.selected.region_id
        if self.source == PASSAGE and self.passage.held is not None:
            return self.passage.held.region_id
        return None


class MapControlPlanner:
    def __init__(self, config: MapControlConfig | None = None) -> None:
        self.config = config or MapControlConfig()
        self._staging = StagingPolicy(self.config)
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
        objective = strategy.objective
        staging, staging_fallback = self._staging.plan(attention, awareness.influence, objective)
        passage = self._passage(attention)
        policy = self.config.policy
        if policy == STAGING:
            anchor = None if staging is None else staging.selected.position
            fallback = staging_fallback
        else:
            anchor, fallback = passage.anchor, passage.fallback
        threatened = awareness.most_threatened
        if objective is Objective.STABILIZE and threatened is not None:
            source, anchor, fallback = THREATENED_BASE, threatened.position, None
        elif anchor is not None:
            source = policy
        else:
            source, anchor = LEGACY, self._legacy(attention)
        held = source if source in POLICIES else "rally"
        reason = f"hold_{held}_{objective.value.lower()}"
        inputs: tuple[tuple[str, float], ...] = (
            ("risk", strategy.risk),
            ("danger", awareness.danger),
        )
        if source == STAGING and staging is not None:
            point = staging.selected
            inputs += (
                ("reaction", point.reaction),
                ("choke", point.choke),
                ("exposure", point.exposure),
                ("score", point.score),
            )
        elif source == PASSAGE and passage.held is not None:
            inputs += (
                ("protected", passage.held.protected),
                ("quality", passage.held.quality),
                ("overextension", passage.held.overextension),
                ("score", passage.held.score),
            )
        return MapControlPlan(
            anchor=anchor,
            source=source,
            reason=reason,
            policy=policy,
            fallback=fallback,
            staging=staging,
            passage=passage,
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

    def _passage(self, attention: AttentionState) -> PassagePlan:
        found = self._evaluate(attention)
        held = self._select(found)
        anchor = None if held is None else self._anchor(attention.map, held)
        return PassagePlan(
            held=held,
            anchor=anchor,
            fallback=(
                "no_separating_passage"
                if held is None
                else "anchor_unresolved"
                if anchor is None
                else None
            ),
            candidates=found,
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

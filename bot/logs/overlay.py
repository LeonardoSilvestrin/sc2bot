"""In-game debug drawing: the influence field as colored spheres on the map.

Presentation only. It reads the frame's layers, queues python-sc2 debug
primitives and derives nothing of its own.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sc2.position import Point2, Point3

from bot.attention import AttentionState
from bot.awareness import AwarenessState
from bot.body.engine import EngineResult
from bot.ego.planners.map_control import MapControlPlan
from bot.ego.strategy import StrategicIntent

Color = tuple[int, int, int]

OWNER_COLORS: dict[str, Color] = {
    "defense": (255, 121, 198),
    "offense": (255, 150, 60),
    "core_army": (138, 212, 255),
    "intel": (255, 214, 102),
}
OTHER_OWNER_COLOR: Color = (195, 166, 255)
TEXT_COLOR: Color = (255, 255, 255)
CONTACT_COLOR: Color = (255, 70, 70)
REMEMBERED_COLOR: Color = (170, 95, 95)
UNCERTAINTY_COLOR: Color = (242, 153, 74)


@dataclass(frozen=True, slots=True)
class OverlayConfig:
    enabled: bool = False
    # Approximate map-unit gap between drawn samples; None draws every one.
    draw_spacing: float | None = 4.0
    show_field: bool = True
    show_contacts: bool = True
    show_owners: bool = True

    def __post_init__(self) -> None:
        if self.draw_spacing is not None and self.draw_spacing <= 0.0:
            raise ValueError("draw_spacing must be positive")


def influence_color(support: float, enemy: float, threat: float) -> Color:
    """Green is ours, red credibly theirs, yellow both, orange only possible."""

    red = max(enemy, threat)
    green = max(support, 0.55 * max(0.0, threat - enemy))
    blue = 1.0 - max(support, enemy, threat)
    return (_channel(70 + 185 * red), _channel(70 + 185 * green), _channel(70 * blue))


def thin(
    positions: Sequence[Point2], spacing: float, draw_spacing: float | None
) -> tuple[int, ...]:
    """Indices of the samples on a coarser lattice about ``draw_spacing`` apart.

    The stride is a whole number of lattice steps, so drawn markers stay a
    regular grid; the bot keeps reasoning over every sample.
    """

    everything = tuple(range(len(positions)))
    if draw_spacing is None or spacing <= 0.0 or not positions:
        return everything
    stride = max(1, int(draw_spacing / spacing + 0.5))
    if stride == 1:
        return everything
    min_x = min(point.x for point in positions)
    min_y = min(point.y for point in positions)
    return tuple(
        index
        for index, point in enumerate(positions)
        if round((point.x - min_x) / spacing) % stride == 0
        and round((point.y - min_y) / spacing) % stride == 0
    )


class Overlay:
    def __init__(self, config: OverlayConfig | None = None) -> None:
        self.config = config or OverlayConfig()
        self._positions: tuple[Point2, ...] | None = None
        self._indices: tuple[int, ...] = ()

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def render(
        self,
        bot,
        attention: AttentionState,
        awareness: AwarenessState,
        intent: StrategicIntent,
        map_control: MapControlPlan,
        result: EngineResult,
    ) -> int:
        """Queue this frame's drawing; returns how many samples were drawn."""

        if not self.enabled:
            return 0
        config = self.config
        client = bot.client
        at = _terrain(bot)
        drawn = 0
        influence = awareness.influence
        if config.show_field:
            if self._positions is not influence.positions:
                self._positions = influence.positions
                self._indices = thin(influence.positions, influence.spacing, config.draw_spacing)
            for index in self._indices:
                support = float(influence.support[index])
                enemy = float(influence.enemy[index])
                threat = float(influence.threat[index])
                client.debug_sphere_out(
                    at(influence.positions[index], 0.2),
                    0.2 + 0.5 * max(support, enemy, threat),
                    influence_color(support, enemy, threat),
                )
                drawn += 1
        if config.show_contacts:
            for contact in awareness.contacts:
                if contact.is_structure or contact.power <= 0.0:
                    continue
                client.debug_sphere_out(
                    at(contact.position, 0.5),
                    0.6 + 0.4 * contact.power**0.5,
                    CONTACT_COLOR if contact.visible else REMEMBERED_COLOR,
                )
                if contact.uncertainty > 0.0:
                    client.debug_sphere_out(
                        at(contact.position, 0.5), contact.uncertainty, UNCERTAINTY_COLOR
                    )
        for base in awareness.bases:
            client.debug_text_world(
                f"{'MAIN' if base.is_main else 'BASE'} threat {base.threat:.2f}\n"
                f"pressure {base.pressure:.1f} cover {base.cover:.1f}",
                at(base.position, 1.5),
                TEXT_COLOR,
                12,
            )
        anchor = map_control.anchor
        client.debug_sphere_out(at(anchor, 0.3), 1.2, TEXT_COLOR)
        staging = map_control.staging
        switch = "" if staging is None else f" {staging.switch}"
        client.debug_text_world(
            f"ANCHOR {map_control.reason}{switch}", at(anchor, 1.0), TEXT_COLOR, 12
        )
        if config.show_owners:
            owner_of = {grant.proposal.proposal_id: grant.proposal.owner for grant in result.grants}
            positions = {unit.tag: unit.position for unit in attention.own_units}
            for tag, proposal_id in result.owners:
                position = positions.get(tag)
                if position is not None:
                    client.debug_sphere_out(
                        at(position, 0.1),
                        0.9,
                        OWNER_COLORS.get(owner_of.get(proposal_id, ""), OTHER_OWNER_COLOR),
                    )
        client.debug_text_screen(
            panel_text(awareness, intent, result), (0.01, 0.16), TEXT_COLOR, 12
        )
        return drawn


def panel_text(awareness: AwarenessState, intent: StrategicIntent, result: EngineResult) -> str:
    visible = sum(contact.visible for contact in awareness.contacts)
    assessment = intent.assessment
    lines = [
        f"STRATEGY {intent.posture.value} ({intent.reason})"
        + (" EMERGENCY" if intent.emergency else ""),
        f"threat {assessment.threat.value} {assessment.threat_level:.2f}  "
        f"army {assessment.army_position:+.2f}  economy {assessment.economy_position:+.2f}",
        f"spike {assessment.power_spike:.2f}  vulnerable {assessment.enemy_vulnerability:.2f}  "
        f"setback {assessment.setback:.2f}  confidence {assessment.confidence:.2f}",
        f"defense {intent.defense:.2f}  army {intent.army:.2f}  risk {intent.risk:.2f}",
        f"contacts {len(awareness.contacts)} ({visible} visible)  "
        f"enemy power {awareness.enemy_power:.1f} (est {awareness.estimated_enemy_power:.1f})",
    ]
    opening = awareness.opening
    if opening.observed:
        lines.append(
            f"OPENING {opening.race.name} aggression {opening.aggression:.2f}  "
            f"greed {opening.greed:.2f}  tech {opening.tech:.2f}  "
            f"proxy {opening.proxy:.2f}  confidence {opening.confidence:.2f}"
        )
    lines.append("ENGINE")
    for grant in result.grants:
        proposal = grant.proposal
        lines.append(
            f"  {proposal.proposal_id}: {len(grant.tags)} {proposal.command.value} "
            f"p={proposal.priority:.2f}"
        )
    return "\n".join(lines)


def _terrain(bot) -> Callable[[Point2, float], Point3]:
    def point(position: Point2, offset: float) -> Point3:
        return Point3(
            (
                float(position.x),
                float(position.y),
                float(bot.get_terrain_z_height(position)) + offset,
            )
        )

    return point


def _channel(value: float) -> int:
    return int(min(255.0, max(0.0, value)))

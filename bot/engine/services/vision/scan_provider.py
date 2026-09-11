from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId

from bot.ports.logging import BotLogger
from bot.ports.vision_commands import VisionCommands
from bot.world.attention import WorldFacts

from .model import ProviderDispatchResult, VisionRequest

COMPONENT = "engine.services.vision.scan_provider"
_ORBITAL_TYPES = frozenset(
    {UnitTypeId.ORBITALCOMMAND, UnitTypeId.ORBITALCOMMANDFLYING}
)


@dataclass(frozen=True, slots=True)
class ScanProviderConfig:
    scan_energy_cost: float = 50.0
    reserve_energy: float = 50.0

    def __post_init__(self) -> None:
        if self.scan_energy_cost <= 0.0 or self.reserve_energy < 0.0:
            raise ValueError("invalid scan energy policy")

    @property
    def required_energy(self) -> float:
        return self.scan_energy_cost + self.reserve_energy


@dataclass(slots=True)
class ScanProvider:
    """Fulfil active-vision requests with the best available Orbital."""

    config: ScanProviderConfig = field(default_factory=ScanProviderConfig)
    logger: BotLogger | None = None
    _now: float = field(default=0.0, init=False, repr=False)
    _commands: VisionCommands | None = field(default=None, init=False, repr=False)
    _energy_by_tag: dict[int, float] = field(
        default_factory=dict, init=False, repr=False
    )

    def begin_frame(self, world: WorldFacts, commands: VisionCommands) -> None:
        self._now = world.time
        self._commands = commands
        self._energy_by_tag = {
            structure.tag: structure.energy
            for structure in world.own_structures
            if structure.unit_type in _ORBITAL_TYPES and structure.is_ready
        }

    def dispatch(self, request: VisionRequest) -> ProviderDispatchResult:
        commands = self._commands
        if commands is None:
            return ProviderDispatchResult(
                accepted=False,
                reason="provider_frame_not_started",
                provider="scanner_sweep",
            )
        eligible = tuple(
            (tag, energy)
            for tag, energy in self._energy_by_tag.items()
            if energy >= self.config.required_energy
        )
        if not eligible:
            return ProviderDispatchResult(
                accepted=False,
                reason="insufficient_orbital_energy",
                provider="scanner_sweep",
            )
        orbital_tag, energy = min(eligible, key=lambda item: (-item[1], item[0]))
        self._event(
            "vision.provider_selected",
            request,
            orbital_tag=orbital_tag,
            orbital_energy=energy,
        )
        accepted = commands.scan(orbital_tag=orbital_tag, target=request.position)
        if not accepted:
            return ProviderDispatchResult(
                accepted=False,
                reason="scanner_sweep_command_rejected",
                provider="scanner_sweep",
                orbital_tag=orbital_tag,
                orbital_energy=energy,
            )
        self._energy_by_tag[orbital_tag] = energy - self.config.scan_energy_cost
        self._event(
            "vision.scan_executed",
            request,
            orbital_tag=orbital_tag,
            orbital_energy=energy,
        )
        return ProviderDispatchResult(
            accepted=True,
            reason="scanner_sweep_dispatched",
            provider="scanner_sweep",
            orbital_tag=orbital_tag,
            orbital_energy=energy,
        )

    def _event(self, name: str, request: VisionRequest, **data: object) -> None:
        if self.logger is None:
            return
        self.logger.event(
            name,
            component=COMPONENT,
            game_time=self._now,
            data={
                "request_id": request.request_id,
                "provider": "scanner_sweep",
                **data,
            },
        )

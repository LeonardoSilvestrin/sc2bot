from __future__ import annotations

from bot.ports.logging import BotLogger
from bot.world.awareness import AwarenessSnapshot

from .gate import ChangeGate


class BeliefTelemetry:
    """Dumps the full economy/army belief, including *why it has not changed
    yet* (raw vs stable, confidence), alongside the transition-only
    ``awareness.belief_changed`` log."""

    def __init__(self, *, logger: BotLogger) -> None:
        self._logger = logger
        self._gate = ChangeGate(heartbeat=10.0)

    def report(self, awareness: AwarenessSnapshot, *, game_time: float) -> None:
        economy = awareness.economy
        army = awareness.army
        signature = (
            economy.relative.raw_state,
            economy.relative.stable_state,
            army.relative.raw_state,
            army.relative.stable_state,
        )
        if not self._gate.admit(signature, now=game_time):
            return
        self._logger.event(
            "awareness.world_belief",
            component="world.awareness.belief",
            game_time=game_time,
            data={
                "economy": {
                    "own_workers": economy.own_workers,
                    "own_bases": economy.own_bases,
                    "enemy_observed_workers": economy.enemy.workers.observed,
                    "enemy_known_workers": round(economy.enemy.workers.known, 1),
                    "enemy_estimated_workers": economy.enemy.workers.estimated,
                    "enemy_workers_uncertainty": round(
                        economy.enemy.workers.uncertainty, 1
                    ),
                    "enemy_confirmed_bases": economy.enemy.bases.confirmed,
                    "enemy_estimated_bases": economy.enemy.bases.estimated,
                    "raw": economy.relative.raw_state.name,
                    "stable": economy.relative.stable_state.name,
                    "advantage": round(economy.relative.advantage, 3),
                    "confidence": round(economy.relative.confidence, 3),
                },
                "army": {
                    "own_supply": round(army.own_supply, 1),
                    "enemy_observed_supply": round(army.enemy.supply.observed, 1),
                    "enemy_known_supply": round(army.enemy.supply.known, 1),
                    "enemy_estimated_supply": round(army.enemy.supply.estimated, 1),
                    "enemy_supply_uncertainty": round(
                        army.enemy.supply.uncertainty, 1
                    ),
                    "raw": army.relative.raw_state.name,
                    "stable": army.relative.stable_state.name,
                    "advantage": round(army.relative.advantage, 3),
                    "confidence": round(army.relative.confidence, 3),
                },
            },
        )

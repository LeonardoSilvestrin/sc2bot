"""Translate Awareness representations into Strategy's normalized contract.

This is the only module at the boundary.  It normalizes observations and
confidence; it does not select, score or prefer an objective.
"""

from __future__ import annotations

from statistics import fmean

from bot.world.awareness import AwarenessSnapshot, BaseSecurityLevel

from .model import StrategyInputs


def build_strategy_inputs(awareness: AwarenessSnapshot) -> StrategyInputs:
    """Build one objective-free set of inputs from an Awareness snapshot."""

    army_confidence = _unit(awareness.army.relative.confidence)
    economy_confidence = _unit(awareness.economy.relative.confidence)
    territory_confidence = _unit(awareness.territory.confidence)
    return StrategyInputs.clamped(
        military_edge=_edge(
            awareness.army.relative.advantage, army_confidence
        ),
        economic_edge=_edge(
            awareness.economy.relative.advantage, economy_confidence
        ),
        territory_edge=_territory_edge(awareness),
        immediate_threat=_immediate_threat(awareness),
        base_exposure=_base_exposure(awareness),
        knowledge_confidence=fmean(
            (army_confidence, economy_confidence, territory_confidence)
        ),
    )


def _edge(advantage: float, confidence: float) -> float:
    """Convert P(ours > theirs) to a confidence-weighted signed edge."""

    return (2.0 * _unit(advantage) - 1.0) * confidence


def _territory_edge(awareness: AwarenessSnapshot) -> float:
    samples = awareness.territory.samples
    if not samples:
        return 0.0
    # Unknown samples contribute neutral territory, not friendly territory.
    return fmean(
        sample.reading.dominance * _unit(sample.reading.confidence)
        for sample in samples
    )


def _immediate_threat(awareness: AwarenessSnapshot) -> float:
    nearby = awareness.threat.near_own_base_enemy_combat_units
    # A few simultaneous attackers already constitute a full tactical event.
    nearby_intensity = min(float(nearby) / 3.0, 1.0)
    base_intensity = 0.0
    for base in awareness.bases:
        if base.threat_score <= 0.0:
            continue
        balance = base.threat_score / max(
            base.threat_score + base.protection_score, 1.0
        )
        severity_floor = (
            1.0
            if base.security is BaseSecurityLevel.CRITICAL
            else 0.5
        )
        base_intensity = max(base_intensity, balance, severity_floor)
    return max(nearby_intensity, base_intensity)


def _base_exposure(awareness: AwarenessSnapshot) -> float:
    """Worst observed reachability/security reading across held bases."""

    by_id = {base.base_id: base for base in awareness.territory.bases}
    exposure = 0.0
    for base in awareness.bases:
        territory = by_id.get(base.base_id)
        if territory is not None and territory.region is not None:
            region = territory.region
            exposure = max(
                exposure,
                _unit(region.ground_access) * _unit(region.reading.confidence),
            )
        if base.security is BaseSecurityLevel.CRITICAL:
            exposure = 1.0
        elif base.security is BaseSecurityLevel.THREATENED:
            exposure = max(exposure, 0.5)
    return exposure


def _unit(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


__all__ = ["build_strategy_inputs"]

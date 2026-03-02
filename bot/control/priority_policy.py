from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.utils.proposals import Proposal


@dataclass(frozen=True)
class PriorityPolicyConfig:
    defense_threat_start_at: int = 65
    defense_threat_full_at: int = 90
    defense_weight_boost: float = 1.35
    macro_threat_dampen: float = 0.42

    depot_supply_left_low: int = 2
    depot_supply_weight_boost: float = 0.55

    executor_opening_boost: float = 0.10
    executor_pressure_dampen: float = 0.20
    executor_bank_dampen_gain: float = 0.30
    executor_bank_target_minerals: int = 700
    executor_bank_target_gas: int = 240
    parity_army_behind_defense_boost: float = 0.70
    parity_army_behind_macro_army_boost: float = 0.55
    parity_army_behind_macro_econ_dampen: float = 0.40
    parity_army_behind_tech_dampen: float = 0.45
    parity_econ_behind_macro_econ_boost: float = 0.40
    parity_econ_behind_expand_boost: float = 0.28
    parity_econ_behind_army_dampen: float = 0.24
    parity_mode_aggressive_army_boost: float = 0.42
    parity_mode_aggressive_harass_boost: float = 0.50
    parity_mode_aggressive_econ_dampen: float = 0.24
    parity_mode_macro_econ_boost: float = 0.36
    parity_mode_macro_expand_boost: float = 0.30
    parity_mode_macro_army_dampen: float = 0.16
    rush_bank_army_boost: float = 0.55
    rush_bank_econ_dampen: float = 0.40
    rush_bank_tech_dampen: float = 0.45

    min_domain_weight: float = 0.45
    max_domain_weight: float = 2.75


@dataclass(frozen=True)
class PriorityDecision:
    effective_score: float
    domain_weight: float
    proposal_bias: float
    bank_pi_output: float
    notes: List[str] = field(default_factory=list)


class PriorityPolicy:
    def __init__(self, cfg: PriorityPolicyConfig = PriorityPolicyConfig()):
        self.cfg = cfg
        self._tick_now: float = -1.0
        self._cached_bank_pressure: float = 0.0

    def begin_tick(self, *, attention: Attention, awareness: Awareness, now: float) -> None:
        nowf = float(now)
        if self._tick_now == nowf:
            return
        self._tick_now = nowf
        self._cached_bank_pressure = self._bank_pressure(attention=attention, awareness=awareness, now=nowf)
        awareness.mem.set(K("control", "priority", "bank_pi_output"), value=float(self._cached_bank_pressure), now=nowf, ttl=5.0)

    def evaluate(self, *, proposal: Proposal, attention: Attention, awareness: Awareness, now: float) -> PriorityDecision:
        self.begin_tick(attention=attention, awareness=awareness, now=now)
        domain = str(proposal.domain)
        proposal_id = str(proposal.proposal_id)
        notes: List[str] = []

        domain_weight = 1.0
        proposal_bias = 0.0

        urgency = int(attention.combat.primary_urgency)
        threat_factor = self._threat_factor(urgency=urgency)
        parity_army_behind = float(
            awareness.mem.get(K("strategy", "parity", "severity", "army_behind"), now=now, default=0.0) or 0.0
        )
        parity_econ_behind = float(
            awareness.mem.get(K("strategy", "parity", "severity", "econ_behind"), now=now, default=0.0) or 0.0
        )
        parity_army_behind = self._clamp(parity_army_behind, low=0.0, high=1.0)
        parity_econ_behind = self._clamp(parity_econ_behind, low=0.0, high=1.0)
        parity_state = str(
            awareness.mem.get(K("strategy", "parity", "state"), now=now, default="TRADEOFF_MIXED") or "TRADEOFF_MIXED"
        ).upper()
        macro_mode = str(awareness.mem.get(K("macro", "desired", "mode"), now=now, default="STANDARD") or "STANDARD").upper()
        rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        aggression_state = str(awareness.mem.get(K("enemy", "aggression", "state"), now=now, default="NONE") or "NONE").upper()
        aggression_source = awareness.mem.get(K("enemy", "aggression", "source"), now=now, default={}) or {}
        if not isinstance(aggression_source, dict):
            aggression_source = {}
        rush_is_early = bool(aggression_source.get("rush_is_early", False))
        rush_army_dump = bool(awareness.mem.get(K("macro", "exec", "rush_army_dump"), now=now, default=False))
        if threat_factor > 0.0:
            if domain == "DEFENSE":
                domain_weight += float(self.cfg.defense_weight_boost) * float(threat_factor)
                notes.append("defense_boost_from_threat")
            elif domain.startswith("MACRO") or domain == "TECH_EXECUTOR":
                damp = max(0.0, 1.0 - (float(self.cfg.macro_threat_dampen) * float(threat_factor)))
                domain_weight *= damp
                notes.append("macro_dampen_from_threat")

        if parity_army_behind > 0.0:
            if domain == "DEFENSE":
                domain_weight += float(self.cfg.parity_army_behind_defense_boost) * float(parity_army_behind)
                notes.append("defense_boost_from_parity_army_behind")
            elif domain == "MACRO_ARMY_EXECUTOR":
                domain_weight += float(self.cfg.parity_army_behind_macro_army_boost) * float(parity_army_behind)
                notes.append("macro_army_boost_from_parity_army_behind")
            elif domain == "MACRO_ECON_EXECUTOR":
                damp = max(
                    0.0,
                    1.0 - (float(self.cfg.parity_army_behind_macro_econ_dampen) * float(parity_army_behind)),
                )
                domain_weight *= damp
                notes.append("macro_econ_dampen_from_parity_army_behind")
            elif domain == "TECH_EXECUTOR":
                damp = max(
                    0.0,
                    1.0 - (float(self.cfg.parity_army_behind_tech_dampen) * float(parity_army_behind)),
                )
                domain_weight *= damp
                notes.append("tech_dampen_from_parity_army_behind")

        if parity_econ_behind > 0.0:
            if domain == "MACRO_ECON_EXECUTOR":
                domain_weight += float(self.cfg.parity_econ_behind_macro_econ_boost) * float(parity_econ_behind)
                notes.append("macro_econ_boost_from_parity_econ_behind")
                if parity_state == "BEHIND_BOTH":
                    domain_weight += float(self.cfg.parity_econ_behind_expand_boost) * float(parity_econ_behind)
                    notes.append("expand_boost_from_parity_econ_behind")
            elif domain == "MACRO_ARMY_EXECUTOR":
                damp = max(
                    0.0,
                    1.0 - (float(self.cfg.parity_econ_behind_army_dampen) * float(parity_econ_behind)),
                )
                domain_weight *= damp
                notes.append("macro_army_dampen_from_parity_econ_behind")

        # Mode-conditioned response for mixed parity:
        # AHEAD_ARMY_BEHIND_ECON => aggressive modes pressure, macro modes catch up eco.
        if parity_state == "AHEAD_ARMY_BEHIND_ECON":
            if macro_mode in {"PUNISH", "RUSH_RESPONSE"}:
                if domain == "MACRO_ARMY_EXECUTOR":
                    domain_weight += float(self.cfg.parity_mode_aggressive_army_boost) * float(parity_econ_behind)
                    notes.append("mode_aggressive_army_pressure")
                elif domain == "HARASS":
                    domain_weight += float(self.cfg.parity_mode_aggressive_harass_boost) * float(parity_econ_behind)
                    notes.append("mode_aggressive_harass_pressure")
                elif domain == "MACRO_ECON_EXECUTOR":
                    damp = max(
                        0.0,
                        1.0 - (float(self.cfg.parity_mode_aggressive_econ_dampen) * float(parity_econ_behind)),
                    )
                    domain_weight *= damp
                    notes.append("mode_aggressive_econ_dampen")
            elif macro_mode in {"STANDARD", "DEFENSIVE"}:
                if domain == "MACRO_ECON_EXECUTOR":
                    domain_weight += float(self.cfg.parity_mode_macro_econ_boost) * float(parity_econ_behind)
                    notes.append("mode_macro_econ_catchup")
                elif domain == "MACRO_ARMY_EXECUTOR":
                    damp = max(
                        0.0,
                        1.0 - (float(self.cfg.parity_mode_macro_army_dampen) * float(parity_econ_behind)),
                    )
                    domain_weight *= damp
                    notes.append("mode_macro_army_dampen")
        elif parity_state == "BEHIND_ARMY_AHEAD_ECON":
            # We can trade eco lead for army stabilization.
            if domain == "MACRO_ARMY_EXECUTOR":
                domain_weight += float(self.cfg.parity_mode_aggressive_army_boost) * float(parity_army_behind)
                notes.append("mode_trade_eco_for_army")
            elif domain == "TECH_EXECUTOR":
                damp = max(
                    0.0,
                    1.0 - (float(self.cfg.parity_mode_macro_army_dampen) * float(parity_army_behind)),
                )
                domain_weight *= damp
                notes.append("mode_trade_eco_tech_dampen")

        supply_left = int(attention.economy.supply_left)
        supply_cap = int(attention.economy.supply_cap)
        if domain == "MACRO_DEPOT_CONTROL" and supply_cap < 200 and supply_left <= int(self.cfg.depot_supply_left_low):
            domain_weight += float(self.cfg.depot_supply_weight_boost)
            notes.append("depot_boost_supply_low")

        if rush_army_dump or (rush_is_early and rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}) or aggression_state == "AGGRESSION":
            if domain == "MACRO_ARMY_EXECUTOR":
                domain_weight += float(self.cfg.rush_bank_army_boost)
                notes.append("aggression_army_boost")
            elif domain == "MACRO_ECON_EXECUTOR":
                domain_weight *= max(0.0, 1.0 - float(self.cfg.rush_bank_econ_dampen))
                notes.append("aggression_econ_dampen")
            elif domain == "TECH_EXECUTOR":
                domain_weight *= max(0.0, 1.0 - float(self.cfg.rush_bank_tech_dampen))
                notes.append("aggression_tech_dampen")

        if domain in {"MACRO_EXECUTOR", "MACRO_ARMY_EXECUTOR", "MACRO_ECON_EXECUTOR"}:
            if not bool(attention.macro.opening_done):
                domain_weight += float(self.cfg.executor_opening_boost)
                notes.append("executor_opening_boost")
            pressure_level = int(awareness.mem.get(K("control", "pressure", "level"), now=now, default=1) or 1)
            if pressure_level >= 3:
                domain_weight *= max(0.65, 1.0 - float(self.cfg.executor_pressure_dampen))
                notes.append("executor_pressure_dampen")
            if float(self._cached_bank_pressure) > 0.0:
                damp = max(0.70, 1.0 - (float(self.cfg.executor_bank_dampen_gain) * float(self._cached_bank_pressure)))
                domain_weight *= damp
                notes.append("executor_bank_dampen")

        override_domain_weight = awareness.mem.get(
            K("control", "priority", "override", "domain_weight", domain),
            now=now,
            default=None,
        )
        if isinstance(override_domain_weight, (int, float)) and float(override_domain_weight) > 0.0:
            domain_weight *= float(override_domain_weight)
            notes.append("domain_override")

        override_bias = awareness.mem.get(
            K("control", "priority", "override", "proposal_bias", proposal_id),
            now=now,
            default=0.0,
        )
        if isinstance(override_bias, (int, float)):
            proposal_bias += float(override_bias)
            if float(override_bias) != 0.0:
                notes.append("proposal_override")

        domain_weight = self._clamp(
            float(domain_weight),
            low=float(self.cfg.min_domain_weight),
            high=float(self.cfg.max_domain_weight),
        )
        effective_score = (float(proposal.score) * float(domain_weight)) + float(proposal_bias)

        awareness.mem.set(K("control", "priority", "effective_score", proposal_id), value=float(effective_score), now=now, ttl=5.0)
        awareness.mem.set(K("control", "priority", "domain_weight", proposal_id), value=float(domain_weight), now=now, ttl=5.0)
        awareness.mem.set(K("control", "priority", "proposal_bias", proposal_id), value=float(proposal_bias), now=now, ttl=5.0)
        awareness.mem.set(
            K("control", "priority", "components", proposal_id),
            value={
                "threat_factor": float(threat_factor),
                "parity_army_behind": float(parity_army_behind),
                "parity_econ_behind": float(parity_econ_behind),
                "parity_state": str(parity_state),
                "macro_mode": str(macro_mode),
                "rush_state": str(rush_state),
                "aggression_state": str(aggression_state),
                "rush_army_dump": bool(rush_army_dump),
                "bank_pressure": float(self._cached_bank_pressure),
                "domain": str(domain),
            },
            now=now,
            ttl=5.0,
        )
        awareness.mem.set(K("control", "priority", "notes", proposal_id), value=list(notes), now=now, ttl=5.0)

        return PriorityDecision(
            effective_score=float(effective_score),
            domain_weight=float(domain_weight),
            proposal_bias=float(proposal_bias),
            bank_pi_output=float(self._cached_bank_pressure),
            notes=list(notes),
        )

    def _bank_pressure(self, *, attention: Attention, awareness: Awareness, now: float) -> float:
        target_m = int(
            awareness.mem.get(
                K("macro", "desired", "bank_target_minerals"),
                now=now,
                default=self.cfg.executor_bank_target_minerals,
            )
            or self.cfg.executor_bank_target_minerals
        )
        target_g = int(
            awareness.mem.get(
                K("macro", "desired", "bank_target_gas"),
                now=now,
                default=self.cfg.executor_bank_target_gas,
            )
            or self.cfg.executor_bank_target_gas
        )
        target_m = max(1, int(target_m))
        target_g = max(1, int(target_g))
        e_m = max(0.0, float(attention.economy.minerals - target_m) / float(target_m))
        e_g = max(0.0, float(attention.economy.gas - target_g) / float(target_g))
        return self._clamp((0.8 * e_m) + (0.2 * e_g), low=0.0, high=1.0)

    def _threat_factor(self, *, urgency: int) -> float:
        start = int(self.cfg.defense_threat_start_at)
        full = int(self.cfg.defense_threat_full_at)
        if urgency <= start:
            return 0.0
        den = max(1, full - start)
        return self._clamp((float(urgency - start)) / float(den), low=0.0, high=1.0)

    @staticmethod
    def _clamp(value: float, *, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

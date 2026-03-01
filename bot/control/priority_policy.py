from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.utils.proposals import Proposal


@dataclass(frozen=True)
class PriorityPolicyConfig:
    # Threat -> prioritize defense and damp macro concurrency.
    defense_threat_start_at: int = 65
    defense_threat_full_at: int = 90
    defense_weight_boost: float = 1.35
    macro_threat_dampen: float = 0.42

    # Supply safety boost for depot-control loop.
    depot_supply_left_low: int = 2
    depot_supply_weight_boost: float = 0.55

    # Bank controller (PI) for macro spending/production pressure.
    bank_target_minerals: int = 650
    bank_target_gas: int = 220
    bank_pi_kp: float = 0.90
    bank_pi_ki: float = 0.35
    bank_pi_integral_cap: float = 3.5
    bank_pi_output_cap: float = 1.0
    bank_spending_gain: float = 0.35
    bank_production_gain: float = 0.20

    # Plan/reserve signals.
    tech_shortfall_weight_boost: float = 0.25
    tech_shortfall_bias: float = 8.0
    expansion_gap_weight_boost: float = 0.18
    expansion_gap_bias: float = 6.0
    natural_recovery_weight_boost: float = 0.10

    # Opening focus.
    opening_production_weight_boost: float = 0.12

    # Hard clamps.
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
        self._cached_bank_pi_output: float = 0.0
        self._cached_lag_tech: float = 0.0
        self._cached_lag_spending: float = 0.0
        self._cached_lag_production: float = 0.0

    def begin_tick(self, *, attention: Attention, awareness: Awareness, now: float) -> None:
        nowf = float(now)
        if self._tick_now == nowf:
            return
        self._tick_now = nowf
        self._cached_bank_pi_output = self._bank_pi_update(attention=attention, awareness=awareness, now=nowf)
        self._publish_resource_arbitration(attention=attention, awareness=awareness, now=nowf)

    def evaluate(self, *, proposal: Proposal, attention: Attention, awareness: Awareness, now: float) -> PriorityDecision:
        self.begin_tick(attention=attention, awareness=awareness, now=now)
        domain = str(proposal.domain)
        proposal_id = str(proposal.proposal_id)
        notes: List[str] = []

        domain_weight = 1.0
        proposal_bias = 0.0

        urgency = int(attention.combat.primary_urgency)
        threat_factor = self._threat_factor(urgency=urgency)
        if threat_factor > 0.0:
            if domain == "DEFENSE":
                domain_weight += self.cfg.defense_weight_boost * threat_factor
                notes.append("defense_boost_from_threat")
            elif domain.startswith("MACRO"):
                damp = max(0.0, 1.0 - (self.cfg.macro_threat_dampen * threat_factor))
                domain_weight *= damp
                notes.append("macro_dampen_from_threat")

        # Keep supply safety hard-prioritized when near block.
        supply_left = int(attention.economy.supply_left)
        supply_cap = int(attention.economy.supply_cap)
        if domain == "MACRO_DEPOT_CONTROL" and supply_cap < 200 and supply_left <= int(self.cfg.depot_supply_left_low):
            domain_weight += float(self.cfg.depot_supply_weight_boost)
            notes.append("depot_boost_supply_low")

        # Bank PI controller: turns bank error into limited global pressure.
        bank_pi_output = float(self._cached_bank_pi_output)
        if domain == "MACRO_SPENDING":
            domain_weight *= 1.0 + (float(self.cfg.bank_spending_gain) * bank_pi_output)
            notes.append("spending_pi")
        elif domain == "MACRO_PRODUCTION":
            domain_weight *= 1.0 + (float(self.cfg.bank_production_gain) * bank_pi_output)
            notes.append("production_pi")

        # Plan shortfall: if tech reserve exists and we are below reserve, boost tech lane.
        tech_shortfall = self._tech_shortfall(attention=attention, awareness=awareness, now=now)
        if tech_shortfall > 0.0 and domain == "MACRO_TECH":
            domain_weight += float(self.cfg.tech_shortfall_weight_boost)
            notes.append("tech_shortfall_weight")
        if tech_shortfall > 0.0 and proposal_id.startswith("tech_planner:"):
            proposal_bias += float(self.cfg.tech_shortfall_bias)
            notes.append("tech_shortfall_bias")

        # Expansion pressure from spending plan.
        expansion_gap = int(
            awareness.mem.get(K("macro", "spending", "status", "expansion_gap"), now=now, default=awareness.mem.get(K("macro", "reserve", "spending", "expansion_gap"), now=now, default=0))
            or 0
        )
        need_natural = bool(awareness.mem.get(K("macro", "spending", "status", "need_natural_now"), now=now, default=False))
        if expansion_gap > 0 and domain == "MACRO_SPENDING":
            domain_weight += float(self.cfg.expansion_gap_weight_boost)
            notes.append("expansion_gap_weight")
            if need_natural:
                domain_weight += float(self.cfg.natural_recovery_weight_boost)
                notes.append("natural_recovery_weight")
        if expansion_gap > 0 and proposal_id.startswith("spending_planner:"):
            proposal_bias += float(self.cfg.expansion_gap_bias)
            notes.append("expansion_gap_bias")

        # During opening, keep production lane sticky.
        if not bool(attention.macro.opening_done) and domain == "MACRO_PRODUCTION":
            domain_weight += float(self.cfg.opening_production_weight_boost)
            notes.append("opening_production_weight")

        # External overrides (for explicit arbitration experiments without code edits).
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
            domain_weight,
            low=float(self.cfg.min_domain_weight),
            high=float(self.cfg.max_domain_weight),
        )
        effective_score = (float(proposal.score) * float(domain_weight)) + float(proposal_bias)

        # Publish decision for observability/tuning.
        awareness.mem.set(
            K("control", "priority", "effective_score", proposal_id),
            value=float(effective_score),
            now=now,
            ttl=5.0,
        )
        awareness.mem.set(
            K("control", "priority", "domain_weight", proposal_id),
            value=float(domain_weight),
            now=now,
            ttl=5.0,
        )
        awareness.mem.set(
            K("control", "priority", "proposal_bias", proposal_id),
            value=float(proposal_bias),
            now=now,
            ttl=5.0,
        )
        awareness.mem.set(
            K("control", "priority", "bank_pi_output"),
            value=float(bank_pi_output),
            now=now,
            ttl=5.0,
        )
        awareness.mem.set(
            K("control", "priority", "notes", proposal_id),
            value=list(notes),
            now=now,
            ttl=5.0,
        )

        return PriorityDecision(
            effective_score=float(effective_score),
            domain_weight=float(domain_weight),
            proposal_bias=float(proposal_bias),
            bank_pi_output=float(bank_pi_output),
            notes=list(notes),
        )

    def _threat_factor(self, *, urgency: int) -> float:
        start = int(self.cfg.defense_threat_start_at)
        full = int(self.cfg.defense_threat_full_at)
        if urgency <= start:
            return 0.0
        den = max(1, full - start)
        return self._clamp((float(urgency - start)) / float(den), low=0.0, high=1.0)

    def _bank_pi_update(self, *, attention: Attention, awareness: Awareness, now: float) -> float:
        target_m = int(awareness.mem.get(K("macro", "desired", "bank_target_minerals"), now=now, default=self.cfg.bank_target_minerals) or self.cfg.bank_target_minerals)
        target_g = int(awareness.mem.get(K("macro", "desired", "bank_target_gas"), now=now, default=self.cfg.bank_target_gas) or self.cfg.bank_target_gas)
        target_m = max(1, int(target_m))
        target_g = max(1, int(target_g))
        e_m = (float(attention.economy.minerals) - float(target_m)) / float(target_m)
        e_g = (float(attention.economy.gas) - float(target_g)) / float(target_g)
        error = (0.8 * e_m) + (0.2 * e_g)

        k_int = K("control", "priority", "pi", "bank", "integral")
        k_last_t = K("control", "priority", "pi", "bank", "last_t")
        integ_prev = float(awareness.mem.get(k_int, now=now, default=0.0) or 0.0)
        t_prev = awareness.mem.get(k_last_t, now=now, default=None)
        dt = 0.0
        if isinstance(t_prev, (int, float)):
            dt = max(0.0, min(2.0, float(now) - float(t_prev)))

        integ = integ_prev + (error * dt)
        integ = self._clamp(integ, low=-float(self.cfg.bank_pi_integral_cap), high=float(self.cfg.bank_pi_integral_cap))

        out = (float(self.cfg.bank_pi_kp) * error) + (float(self.cfg.bank_pi_ki) * integ)
        out = self._clamp(out, low=-float(self.cfg.bank_pi_output_cap), high=float(self.cfg.bank_pi_output_cap))

        awareness.mem.set(k_int, value=float(integ), now=now, ttl=None)
        awareness.mem.set(k_last_t, value=float(now), now=now, ttl=None)
        awareness.mem.set(K("control", "priority", "pi", "bank", "error"), value=float(error), now=now, ttl=5.0)
        awareness.mem.set(K("control", "priority", "pi", "bank", "target_minerals"), value=int(target_m), now=now, ttl=5.0)
        awareness.mem.set(K("control", "priority", "pi", "bank", "target_gas"), value=int(target_g), now=now, ttl=5.0)

        return float(out)

    def _publish_resource_arbitration(self, *, attention: Attention, awareness: Awareness, now: float) -> None:
        lag_prod = self._production_lag(attention=attention, awareness=awareness, now=now)
        lag_tech = self._tech_lag(attention=attention, awareness=awareness, now=now)
        lag_spend = self._spending_lag(attention=attention, awareness=awareness, now=now)

        self._cached_lag_production = float(lag_prod)
        self._cached_lag_tech = float(lag_tech)
        self._cached_lag_spending = float(lag_spend)

        tech_base_m = int(awareness.mem.get(K("macro", "tech", "plan", "reserve_minerals"), now=now, default=0) or 0)
        tech_base_g = int(awareness.mem.get(K("macro", "tech", "plan", "reserve_gas"), now=now, default=0) or 0)
        tech_name = str(awareness.mem.get(K("macro", "tech", "plan", "reserve_name"), now=now, default="") or "")

        expansion_gap = int(
            awareness.mem.get(
                K("macro", "spending", "status", "expansion_gap"),
                now=now,
                default=awareness.mem.get(K("macro", "reserve", "spending", "expansion_gap"), now=now, default=0),
            )
            or 0
        )
        rush_active = bool(awareness.mem.get(K("macro", "spending", "status", "rush_active"), now=now, default=False))
        spending_base_m = 400 if (int(expansion_gap) > 0 and not rush_active) else 0
        spending_base_g = 0
        spending_name = "EXPAND" if int(spending_base_m) > 0 else ""

        prod_pressure = float(lag_prod)
        tech_factor = self._clamp(1.1 + float(lag_tech) - (0.7 * prod_pressure), low=0.35, high=1.6)
        spend_factor = self._clamp(1.1 + float(lag_spend) - (0.7 * prod_pressure), low=0.25, high=1.6)

        tech_reserve_m = int(round(float(tech_base_m) * tech_factor))
        tech_reserve_g = int(round(float(tech_base_g) * tech_factor))
        if tech_base_m > 0 and tech_reserve_m <= 0:
            tech_reserve_m = min(tech_base_m, 75)
        if tech_base_g > 0 and tech_reserve_g <= 0:
            tech_reserve_g = min(tech_base_g, 50)

        spending_reserve_m = int(round(float(spending_base_m) * spend_factor))
        spending_reserve_g = int(round(float(spending_base_g) * spend_factor))
        if spending_base_m > 0 and spending_reserve_m <= 0:
            spending_reserve_m = min(spending_base_m, 100)

        max_reserve_m = int(max(0, int(attention.economy.minerals * 0.75)))
        max_reserve_g = int(max(0, int(attention.economy.gas * 0.75)))
        tech_reserve_m = max(0, min(int(tech_reserve_m), max_reserve_m))
        spending_reserve_m = max(0, min(int(spending_reserve_m), max(0, max_reserve_m - tech_reserve_m)))
        tech_reserve_g = max(0, min(int(tech_reserve_g), max_reserve_g))
        spending_reserve_g = max(0, min(int(spending_reserve_g), max(0, max_reserve_g - tech_reserve_g)))

        awareness.mem.set(K("macro", "reserve", "tech", "minerals"), value=int(tech_reserve_m), now=now, ttl=8.0)
        awareness.mem.set(K("macro", "reserve", "tech", "gas"), value=int(tech_reserve_g), now=now, ttl=8.0)
        awareness.mem.set(K("macro", "reserve", "tech", "name"), value=str(tech_name if tech_reserve_m > 0 or tech_reserve_g > 0 else ""), now=now, ttl=8.0)

        awareness.mem.set(K("macro", "reserve", "spending", "minerals"), value=int(spending_reserve_m), now=now, ttl=8.0)
        awareness.mem.set(K("macro", "reserve", "spending", "gas"), value=int(spending_reserve_g), now=now, ttl=8.0)
        awareness.mem.set(K("macro", "reserve", "spending", "name"), value=str(spending_name if spending_reserve_m > 0 else ""), now=now, ttl=8.0)

        awareness.mem.set(K("control", "priority", "lag", "production"), value=float(lag_prod), now=now, ttl=5.0)
        awareness.mem.set(K("control", "priority", "lag", "tech"), value=float(lag_tech), now=now, ttl=5.0)
        awareness.mem.set(K("control", "priority", "lag", "spending"), value=float(lag_spend), now=now, ttl=5.0)
        awareness.mem.set(
            K("control", "priority", "reserve", "owner"),
            value={
                "tech": "ego.priority_policy",
                "spending": "ego.priority_policy",
            },
            now=now,
            ttl=8.0,
        )

    def _production_lag(self, *, attention: Attention, awareness: Awareness, now: float) -> float:
        comp = awareness.mem.get(K("macro", "desired", "comp"), now=now, default={}) or {}
        if not isinstance(comp, dict) or not comp:
            return 0.0

        units_ready = attention.economy.units_ready
        desired_units = []
        for name, ratio in comp.items():
            if not isinstance(name, str):
                continue
            try:
                uid = getattr(U, str(name))
                target = float(ratio)
            except Exception:
                continue
            if target <= 0.0:
                continue
            desired_units.append((uid, target))

        if not desired_units:
            return 0.0

        total = float(sum(int(units_ready.get(uid, 0) or 0) for uid, _ in desired_units))
        if total <= 0.0:
            return 1.0

        deficit = 0.0
        for uid, target in desired_units:
            cur_prop = float(int(units_ready.get(uid, 0) or 0)) / total
            deficit += max(0.0, float(target) - cur_prop)
        return self._clamp(deficit, low=0.0, high=1.0)

    def _tech_lag(self, *, attention: Attention, awareness: Awareness, now: float) -> float:
        reserve_m = int(awareness.mem.get(K("macro", "tech", "plan", "reserve_minerals"), now=now, default=0) or 0)
        reserve_g = int(awareness.mem.get(K("macro", "tech", "plan", "reserve_gas"), now=now, default=0) or 0)
        reserve_name = str(awareness.mem.get(K("macro", "tech", "plan", "reserve_name"), now=now, default="") or "")
        upgrades = list(awareness.mem.get(K("macro", "tech", "plan", "upgrades"), now=now, default=[]) or [])

        short_m = max(0, reserve_m - int(attention.economy.minerals))
        short_g = max(0, reserve_g - int(attention.economy.gas))
        denom = max(1.0, float(reserve_m + reserve_g))
        short = float(short_m + short_g) / denom if (reserve_m > 0 or reserve_g > 0) else 0.0

        lag = 0.0
        if reserve_name:
            lag += 0.35
        if upgrades:
            lag += 0.10
        lag += 0.80 * short
        return self._clamp(lag, low=0.0, high=1.0)

    def _spending_lag(self, *, attention: Attention, awareness: Awareness, now: float) -> float:
        expansion_gap = int(
            awareness.mem.get(
                K("macro", "spending", "status", "expansion_gap"),
                now=now,
                default=awareness.mem.get(K("macro", "reserve", "spending", "expansion_gap"), now=now, default=0),
            )
            or 0
        )
        need_natural_now = bool(awareness.mem.get(K("macro", "spending", "status", "need_natural_now"), now=now, default=False))
        rush_active = bool(awareness.mem.get(K("macro", "spending", "status", "rush_active"), now=now, default=False))

        lag = self._clamp(float(expansion_gap) / 2.0, low=0.0, high=1.0)
        if need_natural_now:
            lag += 0.25
        if rush_active:
            lag -= 0.20
        return self._clamp(lag, low=0.0, high=1.0)

    @staticmethod
    def _tech_shortfall(*, attention: Attention, awareness: Awareness, now: float) -> float:
        reserve_m = int(awareness.mem.get(K("macro", "reserve", "tech", "minerals"), now=now, default=0) or 0)
        reserve_g = int(awareness.mem.get(K("macro", "reserve", "tech", "gas"), now=now, default=0) or 0)
        if reserve_m <= 0 and reserve_g <= 0:
            return 0.0

        short_m = max(0, reserve_m - int(attention.economy.minerals))
        short_g = max(0, reserve_g - int(attention.economy.gas))
        denom = max(1.0, float(reserve_m + reserve_g))
        return float(short_m + short_g) / denom

    @staticmethod
    def _clamp(value: float, *, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.intel.config.opening_timing_rules import OpeningTimingRule
from bot.intel.utils.enemy_econ_estimates import count_enemy_bases, expected_workers, sum_units
from bot.intel.utils.opening_types import OpeningIntelConfig

_WORKER_TYPES: Tuple[U, ...] = (U.SCV, U.PROBE, U.DRONE)


@dataclass(frozen=True)
class OpeningDecision:
    kind: str
    confidence: float
    rush_state: str
    rush_confidence: float
    rush_score: float
    rush_math: dict
    signals: dict
    last_seen_pressure_t: float


@dataclass(frozen=True)
class OpeningIntelPolicy:
    cfg: OpeningIntelConfig

    def _match_timing_rule(
        self,
        *,
        now: float,
        rule: OpeningTimingRule,
        enemy_race: str,
        enemy_structs: Dict[U, int],
        main_structs: Dict[U, int],
        progress: Dict[U, dict],
    ) -> bool:
        rr = str(rule.race).upper()
        er = str(enemy_race or "UNKNOWN").upper()
        if rr != "ANY" and rr != er:
            return False
        if float(now) < float(rule.earliest_t) or float(now) > float(rule.latest_t):
            return False

        total_count = int(enemy_structs.get(rule.structure, 0))
        main_count = int(main_structs.get(rule.structure, 0))
        max_prog = float((progress.get(rule.structure, {}) or {}).get("max", 0.0) or 0.0)

        if int(total_count) < int(rule.min_total_count):
            return False
        if rule.max_total_count is not None and int(total_count) > int(rule.max_total_count):
            return False
        if int(main_count) < int(rule.min_main_count):
            return False
        if rule.max_main_count is not None and int(main_count) > int(rule.max_main_count):
            return False
        if float(max_prog) < float(rule.min_progress):
            return False
        return True

    def rush_math_signals(self, *, now: float, eb, workers_peak_seen: int = 0, enemy_race: str = "UNKNOWN") -> dict:
        rules = tuple(self.cfg.timing_rules or ())
        if not rules:
            raise RuntimeError("missing_contract:opening_intel.timing_rules")
        enemy_units: Dict[U, int] = dict(getattr(eb, "enemy_units", {}) or {})
        enemy_structs: Dict[U, int] = dict(getattr(eb, "enemy_structures", {}) or {})
        main_units: Dict[U, int] = dict(getattr(eb, "enemy_units_main", {}) or {})
        main_structs: Dict[U, int] = dict(getattr(eb, "enemy_structures_main", {}) or {})
        progress: Dict[U, dict] = dict(getattr(eb, "enemy_structures_progress", {}) or {})

        workers_seen_all = sum_units(enemy_units, _WORKER_TYPES)
        workers_seen_main = sum_units(main_units, _WORKER_TYPES)
        workers_seen_now = int(max(workers_seen_all, workers_seen_main))
        workers_seen = int(max(workers_seen_now, int(workers_peak_seen)))
        expected = expected_workers(float(now), period_s=float(self.cfg.expected_worker_period_s), cap=80)
        worker_deficit = max(0, int(expected) - int(workers_seen))

        enemy_bases = count_enemy_bases(enemy_structs)
        nat_on_ground = bool(getattr(eb, "enemy_natural_on_ground", False))
        nat_prog = float(getattr(eb, "enemy_natural_townhall_progress", 0.0) or 0.0)

        score = 0.0
        matched_rules: list[str] = []
        hard_rush = False

        for rule in rules:
            if not self._match_timing_rule(
                now=float(now),
                rule=rule,
                enemy_race=str(enemy_race),
                enemy_structs=enemy_structs,
                main_structs=main_structs,
                progress=progress,
            ):
                continue
            score += float(rule.score)
            matched_rules.append(str(rule.name))
            if bool(rule.confirm):
                hard_rush = True

        # Worker-count deficit is a weak signal unless combined with an early 1-base posture.
        worker_deficit_score = 0.0
        if (
            worker_deficit >= int(self.cfg.worker_under_count_tolerance)
            and float(now) <= float(self.cfg.worker_deficit_check_until_s)
            and int(enemy_bases) <= 1
            and not bool(nat_on_ground)
        ):
            worker_deficit_score = min(float(self.cfg.worker_deficit_score_cap), float(worker_deficit) * 1.0)
            score += float(worker_deficit_score)
        if int(enemy_bases) <= 1 and not nat_on_ground and float(now) >= float(self.cfg.one_base_alert_at_s):
            score += float(self.cfg.one_base_alert_score)
        if float(now) <= float(self.cfg.no_natural_alert_until_s) and not nat_on_ground and nat_prog <= 0.0:
            score += float(self.cfg.no_natural_alert_score)

        likely_end = bool((nat_on_ground and float(nat_prog) >= 0.90) and worker_deficit <= 2 and enemy_bases >= 2)

        return {
            "workers_seen": int(workers_seen),
            "workers_seen_now": int(workers_seen_now),
            "workers_peak_seen": int(max(0, int(workers_peak_seen))),
            "workers_expected": int(expected),
            "worker_deficit": int(worker_deficit),
            "worker_deficit_score": float(round(worker_deficit_score, 2)),
            "enemy_bases_visible": int(enemy_bases),
            "natural_on_ground": bool(nat_on_ground),
            "natural_progress": float(nat_prog),
            "matched_timing_rules": list(matched_rules),
            "rush_score": float(round(score, 2)),
            "hard_rush": bool(hard_rush),
            "likely_end": bool(likely_end),
        }

    def evaluate(
        self,
        *,
        now: float,
        attention,
        enemy_race: str,
        prev_rush_state: str,
        last_pressure_t: float,
        workers_peak_seen: int,
    ) -> OpeningDecision:
        eb = attention.enemy_build
        enemy_units: Dict[U, int] = eb.enemy_units
        enemy_structs: Dict[U, int] = eb.enemy_structures
        main_units: Dict[U, int] = dict(getattr(eb, "enemy_units_main", {}) or {})

        enemy_bases = count_enemy_bases(enemy_structs)
        near_bases = int(attention.combat.primary_enemy_count)
        threatened = bool(
            int(attention.combat.primary_urgency) >= int(self.cfg.threatened_urgency_min)
            and int(near_bases) >= int(self.cfg.threatened_near_bases_min)
        )

        lings = sum_units(enemy_units, (U.ZERGLING,))
        marines = sum_units(enemy_units, (U.MARINE,))
        reapers = sum_units(enemy_units, (U.REAPER,))
        zealots = sum_units(enemy_units, (U.ZEALOT,))
        adepts = sum_units(enemy_units, (U.ADEPT,))
        stalkers = sum_units(enemy_units, (U.STALKER,))
        main_army_core = sum_units(
            main_units,
            (
                U.ZERGLING,
                U.MARINE,
                U.REAPER,
                U.ZEALOT,
                U.ADEPT,
                U.STALKER,
                U.ROACH,
                U.RAVAGER,
                U.HYDRALISK,
            ),
        )

        early = float(now) <= float(self.cfg.early_s)
        greedy_window = float(now) <= float(self.cfg.greedy_s)
        nat_on_ground = bool(getattr(eb, "enemy_natural_on_ground", False))

        kind = "NORMAL"
        conf = 0.40

        rush_math = self.rush_math_signals(
            now=now,
            eb=eb,
            workers_peak_seen=int(workers_peak_seen),
            enemy_race=str(enemy_race),
        )
        rush_score = float(rush_math["rush_score"])
        hard_rush = bool(rush_math["hard_rush"])

        if early and (near_bases >= int(self.cfg.rush_units_near_bases) or (threatened and near_bases >= 3)):
            kind = "AGGRESSIVE"
            conf = min(0.95, 0.55 + 0.05 * float(near_bases))
            if (lings + marines + reapers + zealots + adepts + stalkers) >= 6:
                conf = min(0.98, conf + 0.10)
        elif hard_rush or rush_score >= float(self.cfg.rush_score_confirmed):
            kind = "AGGRESSIVE"
            conf = min(0.98, 0.62 + (rush_score / 200.0))
        elif greedy_window and (nat_on_ground or enemy_bases >= 2) and near_bases <= 1 and not threatened:
            kind = "GREEDY"
            conf = 0.75

        main_army_refresh_evidence = bool(
            (not nat_on_ground)
            and float(now) <= float(self.cfg.rush_main_army_refresh_no_nat_until_s)
            and int(main_army_core) >= int(self.cfg.rush_main_army_refresh_units_min)
        )
        if int(near_bases) > 0 or bool(threatened) or bool(main_army_refresh_evidence):
            last_pressure_t = float(now)
        clear_for = max(0.0, float(now) - float(last_pressure_t))
        recent_pressure = clear_for <= float(self.cfg.rush_end_clear_s)

        is_suspected = bool(
            rush_score >= float(self.cfg.rush_score_suspected)
            and (early or recent_pressure or int(near_bases) >= 2 or bool(threatened))
        )
        confirmed_with_pressure = bool(
            rush_score >= float(self.cfg.rush_score_confirmed) and (bool(threatened) or int(near_bases) >= 2)
        )
        is_confirmed = bool(hard_rush or confirmed_with_pressure or (threatened and near_bases >= 3))
        rush_likely_end = bool(rush_math["likely_end"]) and clear_for >= float(self.cfg.rush_end_clear_s)
        rush_forced_end = bool(clear_for >= float(self.cfg.rush_hold_max_s) and int(near_bases) <= 1 and not bool(threatened))
        rush_suspected_decay = bool(clear_for >= float(self.cfg.rush_suspect_decay_s) and int(near_bases) <= 1 and not bool(threatened))

        rush_state = str(prev_rush_state or "NONE")
        if is_confirmed:
            rush_state = "CONFIRMED"
        elif is_suspected:
            rush_state = "SUSPECTED" if rush_state in {"NONE", "ENDED"} else "HOLDING"
        elif rush_state in {"CONFIRMED", "SUSPECTED", "HOLDING"}:
            if rush_likely_end or rush_forced_end or (rush_state == "SUSPECTED" and rush_suspected_decay):
                rush_state = "ENDED"
            else:
                rush_state = "HOLDING"
        else:
            rush_state = "NONE"

        rush_conf = min(0.99, max(0.05, 0.30 + rush_score / 100.0 + (0.20 if is_confirmed else 0.0)))
        if rush_state == "NONE":
            rush_conf = min(rush_conf, 0.35)
        if rush_state == "ENDED":
            rush_conf = min(rush_conf, 0.55)

        signals = {
            "t": round(float(now), 2),
            "early": bool(early),
            "greedy_window": bool(greedy_window),
            "enemy_bases_visible": int(enemy_bases),
            "enemy_near_our_bases": int(near_bases),
            "threatened": bool(threatened),
            "natural_on_ground": bool(nat_on_ground),
            "natural_townhall_progress": float(getattr(eb, "enemy_natural_townhall_progress", 0.0) or 0.0),
            "natural_townhall_type": str(getattr(eb, "enemy_natural_townhall_type", None)),
            "seen_units": {
                "lings": int(lings),
                "marines": int(marines),
                "reapers": int(reapers),
                "zealots": int(zealots),
                "adepts": int(adepts),
                "stalkers": int(stalkers),
            },
            "main_units": dict(getattr(eb, "enemy_units_main", {}) or {}),
            "main_army_core": int(main_army_core),
            "main_army_refresh_evidence": bool(main_army_refresh_evidence),
            "main_structures": dict(getattr(eb, "enemy_structures_main", {}) or {}),
            "structures_progress": dict(getattr(eb, "enemy_structures_progress", {}) or {}),
            "rush_math": dict(rush_math),
            "rush_state": str(rush_state),
            "rush_confidence": float(round(rush_conf, 3)),
            "last_seen_pressure_t": float(round(last_pressure_t, 2)),
            "pressure_clear_s": float(round(clear_for, 2)),
            "recent_pressure": bool(recent_pressure),
            "rush_forced_end": bool(rush_forced_end),
            "rush_suspected_decay": bool(rush_suspected_decay),
        }

        return OpeningDecision(
            kind=str(kind),
            confidence=float(conf),
            rush_state=str(rush_state),
            rush_confidence=float(rush_conf),
            rush_score=float(rush_score),
            rush_math=dict(rush_math),
            signals=signals,
            last_seen_pressure_t=float(last_pressure_t),
        )

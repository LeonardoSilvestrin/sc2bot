from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.intel.utils.opening_types import OpeningIntelConfig

_WORKER_TYPES: Tuple[U, ...] = (U.SCV, U.PROBE, U.DRONE)


def count_enemy_bases(enemy_structures: Dict[U, int]) -> int:
    return int(
        enemy_structures.get(U.HATCHERY, 0)
        + enemy_structures.get(U.LAIR, 0)
        + enemy_structures.get(U.HIVE, 0)
        + enemy_structures.get(U.NEXUS, 0)
        + enemy_structures.get(U.COMMANDCENTER, 0)
        + enemy_structures.get(U.ORBITALCOMMAND, 0)
        + enemy_structures.get(U.PLANETARYFORTRESS, 0)
    )


def sum_units(enemy_units: Dict[U, int], types: Tuple[U, ...]) -> int:
    return int(sum(int(enemy_units.get(t, 0)) for t in types))


def expected_workers(now: float, *, period_s: float) -> int:
    out = 12 + int(max(0.0, float(now)) // max(1.0, float(period_s)))
    return int(max(12, min(80, out)))


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

    def rush_math_signals(self, *, now: float, eb, workers_peak_seen: int = 0) -> dict:
        enemy_units: Dict[U, int] = dict(getattr(eb, "enemy_units", {}) or {})
        enemy_structs: Dict[U, int] = dict(getattr(eb, "enemy_structures", {}) or {})
        main_units: Dict[U, int] = dict(getattr(eb, "enemy_units_main", {}) or {})
        progress: Dict[U, dict] = dict(getattr(eb, "enemy_structures_progress", {}) or {})

        workers_seen_all = sum_units(enemy_units, _WORKER_TYPES)
        workers_seen_main = sum_units(main_units, _WORKER_TYPES)
        workers_seen_now = int(max(workers_seen_all, workers_seen_main))
        workers_seen = int(max(workers_seen_now, int(workers_peak_seen)))
        expected = expected_workers(float(now), period_s=float(self.cfg.expected_worker_period_s))
        worker_deficit = max(0, int(expected) - int(workers_seen))

        enemy_bases = count_enemy_bases(enemy_structs)
        nat_on_ground = bool(getattr(eb, "enemy_natural_on_ground", False))
        nat_prog = float(getattr(eb, "enemy_natural_townhall_progress", 0.0) or 0.0)

        z_pool = int(enemy_structs.get(U.SPAWNINGPOOL, 0))
        z_pool_prog = float((progress.get(U.SPAWNINGPOOL, {}) or {}).get("max", 0.0) or 0.0)
        t_rax = int(enemy_structs.get(U.BARRACKS, 0))
        p_gate = int(enemy_structs.get(U.GATEWAY, 0))

        score = 0.0
        if worker_deficit >= int(self.cfg.worker_under_count_tolerance):
            score += min(18.0, float(worker_deficit) * 1.5)
        if int(enemy_bases) <= 1 and not nat_on_ground and float(now) >= 90.0:
            score += 8.0
        if float(now) <= 120.0 and z_pool > 0 and z_pool_prog >= 0.20:
            score += 28.0
        if float(now) <= 130.0 and t_rax >= 2:
            score += 22.0
        if float(now) <= 140.0 and p_gate >= 2:
            score += 22.0
        if float(now) <= 150.0 and not nat_on_ground and nat_prog <= 0.0:
            score += 4.0

        hard_rush = bool(
            (float(now) <= 120.0 and z_pool > 0 and z_pool_prog >= 0.35)
            or (float(now) <= 130.0 and t_rax >= 2)
            or (float(now) <= 140.0 and p_gate >= 2)
        )
        likely_end = bool((nat_on_ground and float(nat_prog) >= 0.90) and worker_deficit <= 2 and enemy_bases >= 2)

        return {
            "workers_seen": int(workers_seen),
            "workers_seen_now": int(workers_seen_now),
            "workers_peak_seen": int(max(0, int(workers_peak_seen))),
            "workers_expected": int(expected),
            "worker_deficit": int(worker_deficit),
            "enemy_bases_visible": int(enemy_bases),
            "natural_on_ground": bool(nat_on_ground),
            "natural_progress": float(nat_prog),
            "z_pool": int(z_pool),
            "z_pool_prog": float(round(z_pool_prog, 3)),
            "t_rax": int(t_rax),
            "p_gate": int(p_gate),
            "rush_score": float(round(score, 2)),
            "hard_rush": bool(hard_rush),
            "likely_end": bool(likely_end),
        }

    def evaluate(
        self,
        *,
        now: float,
        attention,
        prev_rush_state: str,
        last_pressure_t: float,
        workers_peak_seen: int,
    ) -> OpeningDecision:
        eb = attention.enemy_build
        enemy_units: Dict[U, int] = eb.enemy_units
        enemy_structs: Dict[U, int] = eb.enemy_structures

        enemy_bases = count_enemy_bases(enemy_structs)
        near_bases = int(attention.combat.primary_enemy_count)
        threatened = int(attention.combat.primary_urgency) > 0

        lings = sum_units(enemy_units, (U.ZERGLING,))
        marines = sum_units(enemy_units, (U.MARINE,))
        reapers = sum_units(enemy_units, (U.REAPER,))
        zealots = sum_units(enemy_units, (U.ZEALOT,))
        adepts = sum_units(enemy_units, (U.ADEPT,))
        stalkers = sum_units(enemy_units, (U.STALKER,))

        early = float(now) <= float(self.cfg.early_s)
        greedy_window = float(now) <= float(self.cfg.greedy_s)
        nat_on_ground = bool(getattr(eb, "enemy_natural_on_ground", False))

        kind = "NORMAL"
        conf = 0.40

        rush_math = self.rush_math_signals(now=now, eb=eb, workers_peak_seen=int(workers_peak_seen))
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

        if int(near_bases) > 0 or bool(threatened):
            last_pressure_t = float(now)
        clear_for = max(0.0, float(now) - float(last_pressure_t))
        recent_pressure = clear_for <= float(self.cfg.rush_end_clear_s)

        is_suspected = bool(
            rush_score >= float(self.cfg.rush_score_suspected)
            and (early or recent_pressure or int(near_bases) >= 2 or bool(threatened))
        )
        is_confirmed = bool(hard_rush or rush_score >= float(self.cfg.rush_score_confirmed) or (threatened and near_bases >= 3))
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

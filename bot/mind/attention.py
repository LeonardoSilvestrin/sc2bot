# =============================================================================
# bot/mind/attention.py
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict

from sc2.position import Point2

from bot.mind.awareness import Awareness
from bot.sensors.threat_sensor import Threat


# -----------------------------------------------------------------------------
# Economy / Workers (control-grade)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class BaseSat:
    base_id: int                 # stable index in ordering (0,1,2...)
    loc: Tuple[float, float]     # townhall location

    th_tag: int
    geysers_taken: int

    workers_actual: int
    workers_ideal: int

    mineral_actual: int
    mineral_ideal: int

    gas_saturation: Tuple[int, ...]   # e.g. (3,2)
    gas_ideal: Tuple[int, ...]        # e.g. (3,3)
    refinery_tags: Tuple[int, ...]    # aligned with gas arrays


@dataclass(frozen=True)
class EconomySnapshot:
    """
    Tick economy + worker allocation snapshot (read-only).
    Intended to be actionable by housekeeping and planners.
    """
    # Inventory
    units_ready: Dict[object, int]

    # Resources / supply
    minerals: int
    gas: int

    supply_used: int
    supply_cap: int
    supply_left: int
    supply_blocked: bool

    # Workers
    workers_total: int
    workers_idle: int

    # Tags + positions for immediate recovery
    idle_worker_tags: Tuple[int, ...]
    idle_worker_pos: Tuple[Tuple[float, float], ...]

    # Base-level saturation view
    bases_sat: Tuple[BaseSat, ...]

    # Helper lists (bounded) for housekeeping selection
    surplus_mineral_worker_tags: Tuple[int, ...]
    deficit_mineral_worker_tags: Tuple[int, ...]


# -----------------------------------------------------------------------------
# Combat / Intel
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class BaseThreatSnapshot:
    th_tag: int
    th_pos: Point2
    enemy_count: int
    enemy_power: float
    urgency: int
    threat_pos: Optional[Point2]


@dataclass(frozen=True)
class CombatSnapshot:
    primary_base_tag: Optional[int]
    primary_enemy_count: int
    primary_urgency: int
    primary_threat_pos: Optional[Point2]
    base_threats: Tuple[BaseThreatSnapshot, ...]


@dataclass(frozen=True)
class UnitThreatSnapshot:
    mission_id: str
    unit_tag: int
    unit_type: str
    hp_frac: float
    enemy_count_local: int
    danger_score: float
    in_danger: bool


@dataclass(frozen=True)
class MissionUnitThreatSnapshot:
    mission_id: str
    unit_count: int
    units_in_danger: int
    enemy_count_local: int
    worker_targets: int
    can_win_value: Optional[int]
    can_win_fight: Optional[bool]


@dataclass(frozen=True)
class UnitThreatsSnapshot:
    units: Tuple[UnitThreatSnapshot, ...] = ()
    missions: Tuple[MissionUnitThreatSnapshot, ...] = ()


@dataclass(frozen=True)
class IntelSnapshot:
    orbital_ready_to_scan: bool
    orbital_energy: float


# -----------------------------------------------------------------------------
# Macro ops (no economy overlap)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class MacroSnapshot:
    """
    Macro operational state.
    Convenience resource/worker/supply fields are mirrored from EconomySnapshot
    in the same tick to keep planner reads simple.
    """
    opening_done: bool
    bases_total: int

    prod_structures_total: int
    prod_structures_idle: int
    prod_structures_active: int

    minerals: int = 0
    vespene: int = 0
    workers_total: int = 0
    workers_idle: int = 0
    bases_under_saturated: int = 0
    bases_over_saturated: int = 0

    supply_used: int = 0
    supply_cap: int = 0
    supply_left: int = 0
    supply_blocked: bool = False


# -----------------------------------------------------------------------------
# Enemy build (keep as-is; your current enemy_build_sensor fills it)
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class EnemyBuildSnapshot:
    enemy_units: dict
    enemy_structures: dict

    enemy_main_pos: Optional[Point2] = None
    enemy_natural_pos: Optional[Point2] = None

    enemy_units_main: Dict = field(default_factory=dict)
    enemy_structures_main: Dict = field(default_factory=dict)

    enemy_structures_progress: Dict = field(default_factory=dict)

    enemy_natural_on_ground: bool = False
    enemy_natural_townhall_progress: Optional[float] = None
    enemy_natural_townhall_type: Optional[object] = None


@dataclass(frozen=True)
class MissionStatusSnapshot:
    mission_id: str
    proposal_id: str
    domain: str
    status: str
    started_at: Optional[float]
    expires_at: Optional[float]
    remaining_s: Optional[float]
    assigned_count: int
    alive_count: int
    missing_count: int
    original_count: int
    original_alive_count: int
    original_missing_count: int
    original_alive_ratio: float
    mission_degraded: bool
    original_type_counts: Tuple[Tuple[str, int], ...]
    alive_tags: Tuple[int, ...]
    missing_tags: Tuple[int, ...]
    can_reinforce: bool


@dataclass(frozen=True)
class MissionSnapshot:
    ongoing: Tuple[MissionStatusSnapshot, ...] = ()
    ongoing_count: int = 0
    ongoing_units_alive: int = 0
    ongoing_units_missing: int = 0
    needing_support_count: int = 0


@dataclass(frozen=True)
class Attention:
    economy: EconomySnapshot
    combat: CombatSnapshot
    intel: IntelSnapshot
    macro: MacroSnapshot
    enemy_build: EnemyBuildSnapshot
    unit_threats: UnitThreatsSnapshot = field(default_factory=UnitThreatsSnapshot)
    missions: MissionSnapshot = field(default_factory=MissionSnapshot)
    time: float = 0.0


def derive_attention(bot, *, awareness: Awareness, threat: Threat, log=None) -> Attention:
    """
    Derive tick snapshot from sensors.
    Rule: no side-effects.
    """
    from bot.sensors.combat_sensor import derive_combat_snapshot
    from bot.sensors.enemy_build_sensor import derive_enemy_build_sensor
    from bot.sensors.game_state_sensor import derive_game_state_snapshot
    from bot.sensors.mission_sensor import derive_mission_snapshot
    from bot.sensors.unit_threat_sensor import derive_unit_threat_snapshot

    now = float(getattr(bot, "time", 0.0) or 0.0)

    game_state = derive_game_state_snapshot(bot, awareness=awareness)
    combat = derive_combat_snapshot(bot, threat=threat)
    economy = game_state.economy
    intel = game_state.intel
    macro = game_state.macro
    enemy_build = derive_enemy_build_sensor(bot)
    missions = derive_mission_snapshot(bot, awareness=awareness, now=now)
    unit_threats = derive_unit_threat_snapshot(bot, missions=missions)

    out = Attention(
        economy=economy,
        combat=combat,
        unit_threats=unit_threats,
        intel=intel,
        macro=macro,
        enemy_build=enemy_build,
        missions=missions,
        time=float(now),
    )

    if log is not None:
        log.emit(
            "attention_tick",
            {
                "t": round(float(now), 2),
                "primary_urgency": int(combat.primary_urgency),
                "primary_enemy_count": int(combat.primary_enemy_count),
                "minerals": int(economy.minerals),
                "gas": int(economy.gas),
                "supply_left": int(economy.supply_left),
                "opening_done": bool(macro.opening_done),
                "workers_idle": int(economy.workers_idle),
                "bases": int(len(economy.bases_sat)),
                "ongoing_missions": int(missions.ongoing_count),
                "missions_needing_support": int(missions.needing_support_count),
                "threatened_bases": int(sum(1 for b in combat.base_threats if int(b.urgency) > 0)),
            },
            meta={"module": "attention", "component": "attention"},
        )
    return out

"""Detection: how the bot sees what nothing of ours can shoot.

A cloaked or burrowed enemy nothing detects cannot be attacked; the army walks
over it and dies (in `bench/all4/000` a burrowed Lurker sat on the army's path
from 771 s on). Once an enemy army unit was seen cloaked:

- every Orbital Command keeps `scan_reserve` energy instead of spending it all
  on MULEs;
- every base gets a Missile Turret within `turret_cover`, and an Engineering
  Bay is built if there is none;
- a hidden enemy in sight with at least `scan_min_power` of our army within
  `scan_reach` of it is scanned, unless a scan of the last `scan_duration`
  seconds already covers it (`scan_radius`). With several, the one with the
  most of our army near goes first, then the most hidden power a scan there
  reveals, then the lowest tag.

The plan says where to scan and which bases need a turret; the Body picks the
Orbital (the one with the most energy) and the builder.
"""

from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState
from bot.awareness import AwarenessState
from bot.ego.planners import DetectionPlan

# Energy a scan costs.
SCAN_ENERGY = 50.0
ORBITALS = frozenset({UnitTypeId.ORBITALCOMMAND})
TURRETS = frozenset({UnitTypeId.MISSILETURRET})
ENGINEERING_BAYS = frozenset({UnitTypeId.ENGINEERINGBAY})


@dataclass(frozen=True, slots=True)
class DetectionConfig:
    # A hidden enemy with at least `scan_min_power` of our army, in Marines,
    # within `scan_reach` of it is worth a scan: something will shoot it.
    scan_reach: float = 10.0
    scan_min_power: float = 2.0
    # What a scan reveals, and for how long, in cells and seconds.
    scan_radius: float = 13.0
    scan_duration: float = 12.3
    # Energy each Orbital keeps for a scan once a cloaked enemy was seen.
    scan_reserve: float = 50.0
    # A Missile Turret this close to a base covers it.
    turret_cover: float = 15.0

    def __post_init__(self) -> None:
        for name in ("scan_reach", "scan_radius", "turret_cover"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        for name in ("scan_min_power", "scan_duration", "scan_reserve"):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must not be negative")


class Detection:
    def __init__(self, config: DetectionConfig | None = None) -> None:
        self.config = config or DetectionConfig()
        # (time, position) of the scans ordered.
        self._scans: list[tuple[float, Point2]] = []

    def plan(self, attention: AttentionState, awareness: AwarenessState) -> DetectionPlan:
        config = self.config
        now = attention.time
        self._scans = [
            (then, point) for then, point in self._scans if now - then < config.scan_duration
        ]
        cloak_seen = awareness.cloak_seen_at is not None
        hidden = awareness.hidden_contacts
        orbitals = sum(
            1
            for structure in attention.own_structures
            if structure.type_id in ORBITALS
            and structure.is_ready
            and structure.energy >= SCAN_ENERGY
        )
        army = [unit for unit in attention.own_units if not unit.is_worker and unit.power > 0.0]
        scan, reason, near = self._scan(hidden, army, orbitals)
        if scan is not None:
            self._scans.append((now, scan))
        turrets: tuple[Point2, ...] = ()
        engineering_bay = False
        if cloak_seen:
            placed = [s.position for s in attention.own_structures if s.type_id in TURRETS]
            turrets = tuple(
                base.position
                for base in attention.bases
                if not any(base.position.distance_to(p) <= config.turret_cover for p in placed)
            )
            engineering_bay = not any(
                s.type_id in ENGINEERING_BAYS for s in attention.own_structures
            )
        elif reason == "no_hidden_enemy":
            reason = "no_cloak_seen"
        return DetectionPlan(
            scan=scan,
            turrets=turrets,
            engineering_bay=engineering_bay,
            energy_reserve=config.scan_reserve if cloak_seen else 0.0,
            reason=reason,
            inputs=(
                ("hidden_enemies", float(len(hidden))),
                (
                    "cloak_seen_at",
                    -1.0 if awareness.cloak_seen_at is None else awareness.cloak_seen_at,
                ),
                ("army_near_hidden", near),
                ("orbitals_with_scan", float(orbitals)),
                ("active_scans", float(len(self._scans) - (scan is not None))),
            ),
        )

    def _scan(self, hidden, army, orbitals: int) -> tuple[Point2 | None, str, float]:
        """Where to scan, why, and the most of our army near a hidden enemy."""

        config = self.config
        if not hidden:
            return None, "no_hidden_enemy", 0.0
        best: tuple[float, float, int] | None = None
        target: Point2 | None = None
        most_near = 0.0
        uncovered = False
        for contact in hidden:
            if any(
                contact.position.distance_to(point) <= config.scan_radius
                for _, point in self._scans
            ):
                continue
            uncovered = True
            near = sum(
                unit.power
                for unit in army
                if unit.position.distance_to(contact.position) <= config.scan_reach
            )
            most_near = max(most_near, near)
            if near < config.scan_min_power:
                continue
            revealed = sum(
                other.power
                for other in hidden
                if other.position.distance_to(contact.position) <= config.scan_radius
            )
            key = (near, revealed, -contact.tag)
            if best is None or key > best:
                best, target = key, contact.position
        if not uncovered:
            return None, "hidden_enemy_scanned", most_near
        if target is None:
            return None, "no_army_near_hidden", most_near
        if orbitals == 0:
            return None, "no_scan_energy", most_near
        return target, "scan_hidden_enemy", most_near

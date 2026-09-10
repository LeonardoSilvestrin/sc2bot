from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId

from bot.engine.missions.models import MissionKind


@dataclass(frozen=True, slots=True)
class HarassOption:
    """One raid `HarassPlanner` can call once its own gates pass.

    `require_ready_unit` mirrors two different safety postures: Reaper
    harass only ever has one or two precious Reapers, so it withholds unless
    one is genuinely idle and healthy right now (never steals the Reaper
    mid-scout to propose a raid that would just get preempted). Banshees are
    produced in numbers for their playstyle, so proposing as soon as any
    exists is fine -- the allocator's own `UnitRequirement` still filters for
    a healthy/ready one at assignment time, and a proposal that can't
    actually be satisfied just times out and retries next cadence.

    `anti_air_check_radius` scopes the "is the target currently defended"
    check to near the target itself. `None` skips the check entirely (ground
    harass tolerates local ground defenders by design).
    """

    name: str
    mission_kind: MissionKind
    reason: str
    unit_types: frozenset[UnitTypeId]
    minimum_workers: int = 16
    proposal_cadence: float = 45.0
    priority: int = 60
    mission_timeout: float = 60.0
    failure_cooldown: float = 30.0
    minimum_unit_health: float = 0.5
    commitment_seconds: float = 5.0
    require_ready_unit: bool = True
    anti_air_check_radius: float | None = None
    strategic_intent: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not self.reason.strip():
            raise ValueError("reason must not be empty")
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if self.minimum_workers < 1:
            raise ValueError("minimum_workers must be at least 1")
        if self.proposal_cadence <= 0.0:
            raise ValueError("proposal_cadence must be positive")
        if not 0 <= self.priority <= 100 or self.mission_timeout <= 0.0:
            raise ValueError("invalid priority or mission timeout")
        if self.failure_cooldown < 0.0:
            raise ValueError("failure_cooldown must not be negative")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")
        if self.anti_air_check_radius is not None and self.anti_air_check_radius <= 0.0:
            raise ValueError("anti_air_check_radius must be positive")
        if self.strategic_intent is not None and not self.strategic_intent.strip():
            raise ValueError("strategic_intent must not be blank")


def default_harass_options() -> tuple[HarassOption, ...]:
    return (
        HarassOption(
            name="reaper",
            mission_kind=MissionKind.HARASS,
            reason="enemy_worker_line_known_and_reaper_available",
            unit_types=frozenset({UnitTypeId.REAPER}),
            minimum_workers=16,
            priority=60,
            mission_timeout=60.0,
            require_ready_unit=True,
        ),
        HarassOption(
            name="banshee",
            mission_kind=MissionKind.AIR_HARASS,
            reason="enemy_worker_line_known_and_no_visible_anti_air",
            unit_types=frozenset({UnitTypeId.BANSHEE}),
            minimum_workers=12,
            priority=62,
            mission_timeout=70.0,
            require_ready_unit=False,
            # A flying, cloaked harasser cannot be threatened by a ground-only
            # defender, so this only withholds on anti-air actually near the
            # target -- see `CloakedBansheeHarassExecutor.disengage_radius`
            # for the matching in-flight check.
            anti_air_check_radius=15.0,
            strategic_intent="banshee_harass",
        ),
    )


@dataclass(frozen=True, slots=True)
class HarassPlannerConfig:
    """Thresholds shared by every raid `HarassPlanner` can call."""

    target_key: str = "enemy_natural"
    options: tuple[HarassOption, ...] = field(default_factory=default_harass_options)

    def __post_init__(self) -> None:
        if not self.target_key.strip():
            raise ValueError("target_key must not be empty")
        if not self.options:
            raise ValueError("options must not be empty")
        names = [option.name for option in self.options]
        if len(names) != len(set(names)):
            raise ValueError("option names must be unique")

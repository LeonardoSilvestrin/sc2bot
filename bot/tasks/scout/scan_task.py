from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class ScanAt(BaseTask):
    awareness: Awareness
    target: object
    label: str = "scan"
    cooldown: float = 20.0
    log: DevLogger | None = None

    def __init__(
        self,
        *,
        awareness: Awareness,
        target,
        label: str = "scan",
        cooldown: float = 20.0,
        log: DevLogger | None = None,
    ):
        super().__init__(task_id="scan_at", domain="INTEL", commitment=8)
        self.awareness = awareness
        self.target = target
        self.label = str(label)
        self.cooldown = float(cooldown)
        self.log = log

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        now = float(tick.time)

        # Best effort: if no orbital is actually ready, keep mission alive as NOOP.
        orbitals = bot.structures.filter(
            lambda s: getattr(s, "is_ready", False)
            and float(getattr(s, "energy", 0.0) or 0.0) >= 50.0
            and (s.type_id.name in {"ORBITALCOMMAND", "ORBITALCOMMANDFLYING"})
        )
        if not orbitals:
            return TaskResult.noop("no_orbital_ready_to_scan")

        caster = orbitals.sorted(lambda s: float(getattr(s, "energy", 0.0) or 0.0), reverse=True).first
        try:
            caster(AbilityId.SCANNERSWEEP_SCAN, self.target)
        except Exception as e:
            return TaskResult.failed(f"scan_cast_error:{type(e).__name__}", retry_after_s=max(2.0, self.cooldown * 0.25))

        if self.label == "enemy_main":
            try:
                self.awareness.mark_scanned_enemy_main(now=now)
            except Exception:
                pass
        try:
            self.awareness.mem.set(K("intel", "scan", "by_label", str(self.label), "last_t"), value=float(now), now=now, ttl=None)
        except Exception:
            pass

        if self.log is not None:
            try:
                self.log.emit(
                    "scan_cast",
                    {
                        "t": round(float(now), 2),
                        "label": str(self.label),
                        "cooldown": float(self.cooldown),
                        "target": [round(float(self.target.x), 1), round(float(self.target.y), 1)] if hasattr(self.target, "x") else str(self.target),
                    },
                    meta={"module": "task", "component": "task.scan_at"},
                )
            except Exception:
                pass

        return TaskResult.done("scan_cast")

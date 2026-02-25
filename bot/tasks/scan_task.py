# bot/tasks/scan.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.tasks.base_task import BaseTask, TaskTick, TaskResult


@dataclass
class ScanAt(BaseTask):
    awareness: Awareness = None
    target = None
    label: str = "unknown"
    cooldown: float = 20.0
    log: DevLogger | None = None

    # injetado pelo planner/ego (compat)
    mission_id: Optional[str] = None

    def __init__(
        self,
        *,
        awareness: Awareness,
        target,
        label: str,
        cooldown: float = 20.0,
        log: DevLogger | None = None,
    ):
        super().__init__(task_id="scan_at_once", domain="INTEL")
        self.awareness = awareness
        self.target = target
        self.label = str(label)
        self.cooldown = float(cooldown)
        self.log = log
        self.mission_id = None

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        now = float(tick.time)

        last = float(self.awareness.intel_last_scan_at(now=now))
        if (now - last) < float(self.cooldown):
            self._paused("scan_cooldown")
            return TaskResult.noop("scan_cooldown")

        try:
            orbitals = bot.structures(U.ORBITALCOMMAND).ready
        except Exception:
            orbitals = None

        if not orbitals or orbitals.amount == 0:
            self._paused("no_orbital")
            self.awareness.emit(
                "scan_failed",
                now=now,
                data={"label": self.label, "reason": "no_orbital", "mission_id": self.mission_id or ""},
            )
            return TaskResult.failed("no_orbital", retry_after_s=12.0)

        oc = orbitals.first

        try:
            energy = float(getattr(oc, "energy", 0.0) or 0.0)
        except Exception:
            energy = 0.0
        if energy < 50.0:
            self._paused("not_enough_energy")
            return TaskResult.noop("not_enough_energy")

        try:
            oc(AbilityId.SCANNERSWEEP_SCAN, self.target)
        except Exception as e:
            self._paused("scan_command_failed")
            self.awareness.emit(
                "scan_failed",
                now=now,
                data={"label": self.label, "reason": "command_failed", "err": str(e), "mission_id": self.mission_id or ""},
            )
            return TaskResult.failed("scan_command_failed", retry_after_s=10.0)

        self.awareness.mark_scan_enemy_main(now=now)
        self.awareness.emit(
            "scan_cast",
            now=now,
            data={"label": self.label, "mission_id": self.mission_id or ""},
        )

        if self.log:
            self.log.emit("scan_cast", {"t": round(now, 2), "label": self.label, "mission_id": self.mission_id or ""})

        self._done("scan_cast")
        return TaskResult.done("scan_cast")
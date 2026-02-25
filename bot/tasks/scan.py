# bot/tasks/scan.py
from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.tasks.base import BaseTask, TaskTick


@dataclass
class ScanAt(BaseTask):
    awareness: Awareness = None
    target = None
    label: str = "unknown"
    cooldown: float = 20.0
    log: DevLogger | None = None

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

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> bool:
        now = float(tick.time)

        last = float(self.awareness.intel_last_scan_at(now=now))
        if (now - last) < float(self.cooldown):
            self._paused("scan_cooldown")
            return False

        if not attention.orbital_ready_to_scan:
            self._paused("orbital_not_ready")
            return False

        orbitals = bot.structures(U.ORBITALCOMMAND).ready
        if orbitals.amount == 0:
            self._done("no_orbital")
            return False

        oc = orbitals.first
        oc(AbilityId.SCANNERSWEEP_SCAN, self.target)

        self.awareness.mark_scan_enemy_main(now=now)
        if self.log:
            self.log.emit("scan_cast", {"t": round(now, 2), "label": self.label})

        self._done("scan_cast")
        return True
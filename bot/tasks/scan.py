from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId as A
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.tasks.base import TaskStatus, TaskTick


@dataclass
class ScanState:
    done: bool = False


class ScanAt:
    task_id = "scan_at_once"
    domain = "INTEL"
    commitment = 5
    status = TaskStatus.ACTIVE

    def __init__(self, *, awareness: Awareness, target: Point2, label: str, cooldown: float = 20.0):
        self.awareness = awareness
        self.target = target
        self.label = str(label)
        self.cooldown = float(cooldown)
        self.state = ScanState()

    def is_done(self) -> bool:
        return self.status == TaskStatus.DONE or self.state.done

    def evaluate(self, bot, attention: Attention) -> int:
        return 0 if self.is_done() else 1

    async def pause(self, bot, reason: str) -> None:
        self.status = TaskStatus.PAUSED
        bot.log.emit("scan_paused", {"reason": reason, "label": self.label})

    async def abort(self, bot, reason: str) -> None:
        self.status = TaskStatus.DONE
        bot.log.emit("scan_aborted", {"reason": reason, "time": round(bot.time, 2), "label": self.label})

    async def step(self, bot, tick: TaskTick, attention: Attention) -> bool:
        if self.is_done():
            return False

        now = float(bot.time)

        if (now - float(self.awareness.intel.last_scan_at)) < self.cooldown:
            return False

        # usa o sinal derivado (mais limpo)
        if not attention.orbital_ready_to_scan:
            return False

        orbitals = bot.structures(U.ORBITALCOMMAND).ready
        if orbitals.amount == 0:
            return False
        oc = orbitals.first

        oc(A.SCANNERSWEEP_SCAN, self.target)

        # persistência
        if self.label == "enemy_main":
            self.awareness.intel.scanned_enemy_main = True
        self.awareness.intel.last_scan_at = now

        self.state.done = True
        self.status = TaskStatus.DONE

        bot.log.emit(
            "scan_cast",
            {
                "iteration": tick.iteration,
                "time": round(now, 2),
                "label": self.label,
                "target": [round(self.target.x, 1), round(self.target.y, 1)],
                "orbital_energy": float(attention.orbital_energy),
            },
        )
        return True
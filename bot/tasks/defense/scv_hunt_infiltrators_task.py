from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick

_WORKER_TYPES = {U.PROBE, U.DRONE, U.SCV, U.REAPER}
_SCAN_RADIUS = 30.0          # raio de varredura a partir do centro da base
_FOG_MEMORY_S = 8.0          # quanto tempo persiste a última posição vista na fog
_RELEASE_CLEAR_S = 6.0       # segundos sem ver worker para encerrar a task
_PATROL_RADIUS = 8.0         # raio da varredura ao redor do last_seen


@dataclass
class ScvHuntInfiltratorsTask(BaseTask):
    """
    Um único SCV designado para caçar worker infiltrado na base.
    Persiste a última posição vista para continuar o hunt mesmo quando o alvo
    entra na fog. Encerra sozinho se ficar _RELEASE_CLEAR_S sem detecção.
    """

    base_pos: Point2
    log: DevLogger | None = None

    _last_seen_pos: Point2 | None = field(default=None, init=False, repr=False)
    _last_seen_t: float = field(default=0.0, init=False, repr=False)
    _clear_since: float = field(default=0.0, init=False, repr=False)

    def __init__(
        self,
        *,
        base_pos: Point2,
        log: DevLogger | None = None,
    ) -> None:
        super().__init__(task_id="scv_hunt_infiltrators", domain="DEFENSE", commitment=65)
        self.base_pos = base_pos
        self.log = log
        self._last_seen_pos = None
        self._last_seen_t = 0.0
        self._clear_since = 0.0

    @staticmethod
    def _enemy_workers_near(bot, base_pos: Point2):
        try:
            return [
                u for u in bot.enemy_units
                if u.type_id in _WORKER_TYPES
                and float(u.distance_to(base_pos)) <= _SCAN_RADIUS
            ]
        except Exception:
            return []

    def _patrol_sweep(self, scv, *, now: float) -> Point2 | None:
        """Retorna ponto de varredura ao redor do último lugar visto."""
        if self._last_seen_pos is None:
            return None
        if (now - self._last_seen_t) > _FOG_MEMORY_S:
            return None
        return self._last_seen_pos

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound(min_tags=1)
        if bound_err is not None:
            return bound_err

        units = [bot.units.find_by_tag(int(t)) for t in self.assigned_tags]
        scvs = [u for u in units if u is not None and u.type_id == U.SCV]
        if not scvs:
            return TaskResult.failed("no_scv_alive")

        scv = scvs[0]
        now = float(tick.time)

        workers = self._enemy_workers_near(bot, self.base_pos)

        if workers:
            target = min(workers, key=lambda w: float(scv.distance_to(w)))
            self._last_seen_pos = Point2((float(target.position.x), float(target.position.y)))
            self._last_seen_t = now
            self._clear_since = 0.0
            scv.attack(target)
            self._active("hunt_chasing")
            return TaskResult.running("hunt_chasing")

        # Alvo na fog — verifica se ainda vale a pena varrer
        sweep_target = self._patrol_sweep(scv, now=now)
        if sweep_target is not None:
            self._clear_since = 0.0
            if float(scv.distance_to(sweep_target)) > 3.0:
                scv.attack(sweep_target)  # attack-move para revelar area
            else:
                # Chegou no último lugar visto — patrulha ao redor
                sweep_orbit = sweep_target.towards(self.base_pos, -_PATROL_RADIUS * 0.5)
                scv.patrol(sweep_orbit)
            self._active("hunt_sweep")
            return TaskResult.running("hunt_sweep")

        # Sem alvo visível nem memória recente
        if self._clear_since <= 0.0:
            self._clear_since = now
        elif (now - self._clear_since) >= _RELEASE_CLEAR_S:
            self._done("hunt_clear")
            return TaskResult.done("hunt_clear")

        # Enquanto aguarda confirmação de ausência, retorna o SCV para base
        if bool(getattr(scv, "is_idle", True)):
            scv.move(self.base_pos)
        self._active("hunt_idle")
        return TaskResult.running("hunt_idle")

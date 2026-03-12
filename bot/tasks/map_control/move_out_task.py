"""
MoveOutTask — ataque late-game com leapfrog de tanks.

Fluxo:
    CONCENTRATE → ADVANCE (leapfrog) → SIEGE_BASE

Leapfrog:
    1. Bio/mech avança até `leapfrog_pos` (frente do grupo).
    2. Tanks (unsieged) correm para frente do bio — `leapfrog_pos + delta`.
    3. Quando todos os tanks chegaram e siegaram → bio avança para o próximo waypoint.
    4. Repete até atingir a base inimiga (waypoints esgotados ou target alcançado).

Commit:
    Não recua por dano ou urgency moderada.
    Só dá done() quando:
      - bulk perdeu >= 60% do supply inicial (colapso de força)
      - task explicitamente cancelada pelo Ego (abort)
    Nunca abria ao tomar dano normal — o objetivo é atacar até o fim.

Harass lateral:
    Não lida com banshees/drops — isso é responsabilidade do MapControlPlanner
    que propõe MoveOutTask + BansheeHarass em paralelo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Unidades que formam a "tela" (bio ou mech) — avançam e seguram frente
_SCREEN_TYPES = {
    U.MARINE,
    U.MARAUDER,
    U.HELLION,
    U.CYCLONE,
    U.THOR,
    U.THORAP,
    U.WIDOWMINE,
    U.WIDOWMINEBURROWED,
}

_TANK_TYPES = {U.SIEGETANK, U.SIEGETANKSIEGED}
_MEDIVAC_TYPES = {U.MEDIVAC}

# Raios de distância
_SCREEN_AT_POS_RADIUS   = 5.5   # screen considera "chegou"
_TANK_AT_POS_RADIUS     = 6.0   # tank considera "chegou ao leapfrog slot"
_TANK_SIEGE_NEAR_ENEMY  = 13.0  # se inimigo nesse raio: tenta segar mesmo em movimento
_ENEMY_BASE_RADIUS      = 18.0  # considera "na base" para fase SIEGE_BASE
_CONCENTRATE_RADIUS     = 10.0  # considera bulk "concentrado" nesse raio do anchor
_LEAPFROG_DELTA         = 6.0   # tanks avançam N tiles à frente do screen
_LEAPFROG_MAX_WAIT_S    = 12.0  # espera máxima por tanks siegarem antes de avançar mesmo assim
_WAYPOINT_ADVANCE_FRAC  = 0.55  # fracção do caminho para cada waypoint intermediário

# Limiar de colapso: só recua se perdeu 60%+ do exército inicial
_COLLAPSE_THRESHOLD     = 0.40  # restante mínimo para continuar (40% do supply inicial)

# Tempo máximo na fase CONCENTRATE antes de avançar mesmo incompleto
_CONCENTRATE_TIMEOUT_S  = 20.0


class _Phase(str, Enum):
    CONCENTRATE = "CONCENTRATE"   # concentra bulk no anchor de staging
    ADVANCE     = "ADVANCE"       # leapfrog em direção ao alvo
    SIEGE_BASE  = "SIEGE_BASE"    # chegou na base: tanks siegam, screen ataca estruturas


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _supply_of_units(units) -> float:
    """Estima supply consumido por uma coleção de unidades."""
    supply_map = {
        U.MARINE: 1, U.MARAUDER: 2, U.REAPER: 1,
        U.HELLION: 2, U.CYCLONE: 3, U.SIEGETANK: 3, U.SIEGETANKSIEGED: 3,
        U.THOR: 6, U.THORAP: 6, U.MEDIVAC: 2,
        U.WIDOWMINE: 2, U.WIDOWMINEBURROWED: 2,
    }
    total = 0.0
    for u in units:
        total += float(supply_map.get(getattr(u, "type_id", None), 1))
    return total


def _enemy_structures_near(bot, pos: Point2, radius: float):
    try:
        return bot.enemy_structures.closer_than(radius, pos)
    except Exception:
        return []


def _enemy_units_near(bot, pos: Point2, radius: float):
    try:
        return bot.enemy_units.closer_than(radius, pos)
    except Exception:
        return []


def _point_from_payload(payload) -> Point2 | None:
    if not isinstance(payload, dict):
        return None
    try:
        return Point2((float(payload.get("x", 0.0) or 0.0), float(payload.get("y", 0.0) or 0.0)))
    except Exception:
        return None


def _build_waypoints(start: Point2, target: Point2, n_steps: int = 3) -> list[Point2]:
    """Gera waypoints intermediários uniformes entre start e target."""
    waypoints = []
    for i in range(1, n_steps + 1):
        frac = float(i) / float(n_steps + 1)
        wp = Point2((
            float(start.x) + (float(target.x) - float(start.x)) * frac,
            float(start.y) + (float(target.y) - float(start.y)) * frac,
        ))
        waypoints.append(wp)
    waypoints.append(target)
    return waypoints


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

@dataclass
class MoveOutTask(BaseTask):
    """
    Ataque late-game com leapfrog de tanks.

    Parâmetros obrigatórios:
        awareness   — para ler geometria / postura
        target_pos  — base inimiga alvo (mais externa com estruturas)
        start_pos   — posição inicial de concentração (PUSH_STAGING anchor)

    Parâmetros opcionais:
        n_leapfrog_steps — quantos saltos intermediários (padrão: 3)
        log              — DevLogger
    """

    awareness: Awareness
    target_pos: Point2
    start_pos: Point2
    n_leapfrog_steps: int = 3
    log: DevLogger | None = None

    # --- estado interno ---
    _phase: _Phase = field(default=_Phase.CONCENTRATE, init=False, repr=False)
    _waypoints: list[Point2] = field(default_factory=list, init=False, repr=False)
    _current_wp_idx: int = field(default=0, init=False, repr=False)
    _initial_supply: float = field(default=0.0, init=False, repr=False)
    _phase_start_t: float = field(default=0.0, init=False, repr=False)
    _tanks_sieging_since: float = field(default=0.0, init=False, repr=False)
    _iters: int = field(default=0, init=False, repr=False)
    _last_log_t: float = field(default=0.0, init=False, repr=False)

    def __init__(
        self,
        *,
        awareness: Awareness,
        target_pos: Point2,
        start_pos: Point2,
        n_leapfrog_steps: int = 3,
        log: DevLogger | None = None,
    ) -> None:
        super().__init__(task_id="move_out", domain="MAP_CONTROL", commitment=97)
        self.awareness = awareness
        self.target_pos = target_pos
        self.start_pos = start_pos
        self.n_leapfrog_steps = int(n_leapfrog_steps)
        self.log = log
        self._phase = _Phase.CONCENTRATE
        self._waypoints = []
        self._current_wp_idx = 0
        self._initial_supply = 0.0
        self._phase_start_t = 0.0
        self._tanks_sieging_since = 0.0
        self._iters = 0
        self._last_log_t = 0.0

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _bulk(self, bot):
        assigned_set = set(int(t) for t in self.assigned_tags)
        return bot.units.filter(lambda u: int(u.tag) in assigned_set)

    def _current_supply(self, bot) -> float:
        return _supply_of_units(self._bulk(bot))

    def _current_waypoint(self) -> Point2:
        if self._current_wp_idx < len(self._waypoints):
            return self._waypoints[self._current_wp_idx]
        return self.target_pos

    def _advance_waypoint(self) -> None:
        if self._current_wp_idx < len(self._waypoints) - 1:
            self._current_wp_idx += 1

    def _at_final_target(self) -> bool:
        return self._current_wp_idx >= len(self._waypoints) - 1

    # ------------------------------------------------------------------
    # Lógica de colapso (único motivo para recuar)
    # ------------------------------------------------------------------

    def _is_collapsed(self) -> bool:
        if self._initial_supply <= 0.0:
            return False
        # Evita colapso falso no primeiro tick antes de registrar supply inicial
        return False  # Será calculado no on_step com acesso ao bot

    def _check_collapse(self, bot) -> bool:
        if self._initial_supply <= 0.0:
            return False
        current = self._current_supply(bot)
        return (current / self._initial_supply) < _COLLAPSE_THRESHOLD

    # ------------------------------------------------------------------
    # Fases
    # ------------------------------------------------------------------

    def _tick_concentrate(self, bot, now: float) -> TaskResult:
        """Concentra o bulk no start_pos (PUSH_STAGING anchor)."""
        bulk = self._bulk(bot)
        if bulk.amount == 0:
            return TaskResult.failed("no_units")

        # Registra supply inicial uma vez
        if self._initial_supply <= 0.0:
            self._initial_supply = _supply_of_units(bulk)
            self._phase_start_t = now
            # Constrói waypoints agora que temos start e target
            self._waypoints = _build_waypoints(
                self.start_pos, self.target_pos, self.n_leapfrog_steps
            )

        # Verifica concentração: fração do bulk dentro do raio
        units_near = [u for u in bulk if float(u.distance_to(self.start_pos)) <= _CONCENTRATE_RADIUS]
        concentration = float(len(units_near)) / float(max(1, bulk.amount))
        timeout = (now - self._phase_start_t) > _CONCENTRATE_TIMEOUT_S

        if concentration >= 0.75 or timeout:
            # Pronto para avançar
            self._phase = _Phase.ADVANCE
            self._current_wp_idx = 0
            self._phase_start_t = now
            self._tanks_sieging_since = 0.0
            return TaskResult.running("concentrate_done_advancing")

        # Move todos para o start_pos
        for u in bulk:
            try:
                if float(u.distance_to(self.start_pos)) > _CONCENTRATE_RADIUS * 0.6:
                    # Unsiege tanks que precisam se mover
                    if u.type_id == U.SIEGETANKSIEGED:
                        enemy_near = _enemy_units_near(bot, u.position, 10.0)
                        if len(list(enemy_near)) == 0:
                            u(AbilityId.UNSIEGE_UNSIEGE)
                    elif u.type_id == U.WIDOWMINEBURROWED:
                        u(AbilityId.BURROWUP_WIDOWMINE)
                    else:
                        u.move(self.start_pos)
            except Exception:
                continue

        return TaskResult.running("concentrating")

    def _tick_advance(self, bot, now: float) -> TaskResult:
        """Leapfrog: screen avança → tanks correm à frente → tanks siegam → bio avança."""
        bulk = self._bulk(bot)
        if bulk.amount == 0:
            return TaskResult.failed("no_units")

        if self._check_collapse(bot):
            self._done("army_collapsed")
            return TaskResult.done("army_collapsed")

        screen = bulk.of_type(_SCREEN_TYPES)
        tanks  = bulk.of_type(_TANK_TYPES)
        medivacs = bulk.of_type(_MEDIVAC_TYPES)

        wp = self._current_waypoint()

        # --- Checar se chegamos perto o suficiente da base final ---
        if self._at_final_target():
            center = bulk.center if bulk.amount > 0 else self.start_pos
            try:
                dist_to_target = float(center.distance_to(self.target_pos))
            except Exception:
                dist_to_target = 9999.0
            enemy_structs = _enemy_structures_near(bot, self.target_pos, _ENEMY_BASE_RADIUS)
            if dist_to_target <= _ENEMY_BASE_RADIUS or len(list(enemy_structs)) > 0:
                self._phase = _Phase.SIEGE_BASE
                self._phase_start_t = now
                return TaskResult.running("transitioning_to_siege_base")

        # --- Estado do leapfrog ---
        # Verifica se a tela chegou ao waypoint atual
        screen_at_wp = all(
            float(u.distance_to(wp)) <= _SCREEN_AT_POS_RADIUS
            for u in screen
        ) if screen.amount > 0 else True

        # Posição para os tanks: à frente do waypoint em direção ao próximo
        if self._current_wp_idx + 1 < len(self._waypoints):
            next_wp = self._waypoints[self._current_wp_idx + 1]
        else:
            next_wp = self.target_pos
        try:
            tank_target = wp.towards(next_wp, _LEAPFROG_DELTA)
        except Exception:
            tank_target = wp

        # Verifica se tanks chegaram ao seu slot à frente
        tanks_at_slot = all(
            float(u.distance_to(tank_target)) <= _TANK_AT_POS_RADIUS
            for u in tanks.of_type({U.SIEGETANK})
        ) if tanks.of_type({U.SIEGETANK}).amount > 0 else True

        # Verifica se tanks unsieged já siegaram
        tanks_sieged = tanks.of_type({U.SIEGETANKSIEGED})
        tanks_unsieged = tanks.of_type({U.SIEGETANK})
        all_tanks_sieged = (tanks_unsieged.amount == 0) or (tanks.amount == 0)

        if all_tanks_sieged and self._tanks_sieging_since <= 0.0:
            self._tanks_sieging_since = now

        siege_wait_expired = (
            self._tanks_sieging_since > 0.0
            and (now - self._tanks_sieging_since) > _LEAPFROG_MAX_WAIT_S
        )

        # --- Decidir ação por subgrupo ---

        # SCREEN: avança para o waypoint atual (attack-move)
        if not screen_at_wp:
            for u in screen:
                try:
                    if u.type_id == U.WIDOWMINEBURROWED:
                        u(AbilityId.BURROWUP_WIDOWMINE)
                    elif float(u.distance_to(wp)) > _SCREEN_AT_POS_RADIUS:
                        u.attack(wp)
                except Exception:
                    continue

        # TANKS: lógica leapfrog
        for u in tanks:
            try:
                if u.type_id == U.SIEGETANKSIEGED:
                    # Tank siegado: unsiege se ainda não chegou ao slot
                    dist_to_slot = float(u.distance_to(tank_target))
                    enemy_near = _enemy_units_near(bot, u.position, _TANK_SIEGE_NEAR_ENEMY)
                    if dist_to_slot > _TANK_AT_POS_RADIUS and len(list(enemy_near)) == 0:
                        u(AbilityId.UNSIEGE_UNSIEGE)
                elif u.type_id == U.SIEGETANK:
                    dist_to_slot = float(u.distance_to(tank_target))
                    if dist_to_slot > _TANK_AT_POS_RADIUS:
                        # Ainda precisa se mover para o slot
                        u.move(tank_target)
                    else:
                        # Chegou: siega (se não houver inimigo colado)
                        enemy_too_close = _enemy_units_near(bot, u.position, 3.0)
                        if len(list(enemy_too_close)) == 0:
                            u(AbilityId.SIEGEMODE_SIEGEMODE)
            except Exception:
                continue

        # MEDIVACS: seguem o centro do screen
        if medivacs.amount > 0 and screen.amount > 0:
            try:
                follow_pos = screen.center
                for med in medivacs:
                    med.move(follow_pos)
            except Exception:
                pass

        # --- Avançar waypoint quando leapfrog completo ---
        leapfrog_done = screen_at_wp and (all_tanks_sieged or siege_wait_expired)
        if leapfrog_done and not self._at_final_target():
            self._advance_waypoint()
            self._tanks_sieging_since = 0.0  # reset para próximo salto

        return TaskResult.running(f"advancing_wp{self._current_wp_idx}")

    def _tick_siege_base(self, bot, now: float) -> TaskResult:
        """Na base inimiga: tanks siegam, screen ataca estruturas e unidades."""
        bulk = self._bulk(bot)
        if bulk.amount == 0:
            return TaskResult.failed("no_units")

        if self._check_collapse(bot):
            self._done("army_collapsed")
            return TaskResult.done("army_collapsed")

        screen  = bulk.of_type(_SCREEN_TYPES)
        tanks   = bulk.of_type(_TANK_TYPES)
        medivacs = bulk.of_type(_MEDIVAC_TYPES)

        # Alvo prioritário: estruturas → depois unidades → depois target_pos
        enemy_structs = list(_enemy_structures_near(bot, self.target_pos, _ENEMY_BASE_RADIUS + 10.0))
        enemy_units_near_target = list(_enemy_units_near(bot, self.target_pos, _ENEMY_BASE_RADIUS + 10.0))

        def _best_attack_target():
            if enemy_structs:
                try:
                    return min(enemy_structs, key=lambda s: float(bulk.center.distance_to(s)))
                except Exception:
                    return enemy_structs[0]
            if enemy_units_near_target:
                try:
                    return min(enemy_units_near_target, key=lambda e: float(bulk.center.distance_to(e)))
                except Exception:
                    return enemy_units_near_target[0]
            return None

        attack_target = _best_attack_target()

        # TANKS: siega na posição atual, ataca alvos em range
        for u in tanks:
            try:
                if u.type_id == U.SIEGETANK:
                    enemy_too_close = _enemy_units_near(bot, u.position, 3.0)
                    if len(list(enemy_too_close)) == 0:
                        u(AbilityId.SIEGEMODE_SIEGEMODE)
                    elif attack_target is not None:
                        u.attack(attack_target)
                # Siegetanksieged: mantém siege, ataca automaticamente
            except Exception:
                continue

        # SCREEN: attack-move nos alvos
        for u in screen:
            try:
                if u.type_id == U.WIDOWMINE:
                    # Burra mines perto de estruturas para interceptar unidades
                    enemy_near = _enemy_units_near(bot, u.position, 8.0)
                    if len(list(enemy_near)) == 0:
                        u(AbilityId.BURROWDOWN_WIDOWMINE)
                elif u.type_id == U.WIDOWMINEBURROWED:
                    pass  # deixa burrowed
                elif attack_target is not None:
                    if not bool(getattr(u, "is_attacking", False)):
                        u.attack(attack_target)
                else:
                    if not bool(getattr(u, "is_attacking", False)):
                        u.attack(self.target_pos)
            except Exception:
                continue

        # MEDIVACS: ficam perto do screen
        if medivacs.amount > 0 and screen.amount > 0:
            try:
                follow_pos = screen.center
                for med in medivacs:
                    if float(med.distance_to(follow_pos)) > 4.0:
                        med.move(follow_pos)
            except Exception:
                pass

        # Fim: sem mais alvos na área → done (vitória parcial)
        if len(enemy_structs) == 0 and len(enemy_units_near_target) == 0:
            # Verifica se ainda há alguma coisa em qualquer lugar
            try:
                any_structure = bot.enemy_structures.amount
            except Exception:
                any_structure = 1
            if any_structure == 0:
                self._done("enemy_eliminated")
                return TaskResult.done("enemy_eliminated")
            # Procura próxima base com estruturas
            try:
                next_target = min(
                    bot.enemy_structures,
                    key=lambda s: float(bulk.center.distance_to(s)),
                )
                self.target_pos = next_target.position
            except Exception:
                pass

        return TaskResult.running("sieging_base")

    # ------------------------------------------------------------------
    # on_step principal
    # ------------------------------------------------------------------

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        self._iters += 1
        now = float(tick.time)

        guard = self.require_mission_bound(min_tags=1)
        if guard is not None:
            return guard

        if self._phase == _Phase.CONCENTRATE:
            result = self._tick_concentrate(bot, now)
        elif self._phase == _Phase.ADVANCE:
            result = self._tick_advance(bot, now)
        else:
            result = self._tick_siege_base(bot, now)

        # Log periódico
        if self.log is not None and (now - self._last_log_t) >= 5.0:
            self._last_log_t = now
            bulk = self._bulk(bot)
            self.log.emit(
                "move_out_tick",
                {
                    "phase": self._phase.value,
                    "wp_idx": self._current_wp_idx,
                    "wp_total": len(self._waypoints),
                    "bulk_count": int(bulk.amount),
                    "initial_supply": round(float(self._initial_supply), 1),
                    "current_supply": round(float(_supply_of_units(bulk)), 1),
                    "target": {"x": float(self.target_pos.x), "y": float(self.target_pos.y)},
                    "result": str(result.reason),
                },
                meta={"module": "task", "component": "move_out_task"},
            )

        if result.status in {"RUNNING", "NOOP"}:
            self._active(result.reason)
        return result

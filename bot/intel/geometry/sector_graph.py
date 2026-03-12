"""
SectorGraph — deriva as posições concretas dos setores operacionais a partir do mapa.

Responsabilidade: mapear SectorId → Point2 usando dados do mediator/bot.
Não decide quais setores estão ativos — isso é responsabilidade da GeometryIntel.

Posições derivadas:
    HOME_CORE     → start_location
    MAIN_RAMP     → main_base_ramp.top_center
    RETREAT_BUFFER → entre ramp top e nat center
    NAT_FOOTPRINT → mediator.get_own_nat
    NAT_RING      → nat center
    NAT_CHOKE     → choke da nat em direção ao inimigo
    MID_APPROACH  → ponto entre nat choke e centro do mapa
    WATCH_AREA    → ponto de visão avançada (heurístico)
    THIRD_ENTRY   → third expansion entry (heurístico)
    PUSH_STAGING  → entre nat e mid, ~2/3 do caminho para inimigo
"""
from __future__ import annotations

from typing import Optional

from sc2.position import Point2

from bot.intel.geometry.sector_types import SectorId
from bot.intel.utils.natural_geometry import sanitize_natural_defense_point


def _pathable(bot, pos: Point2) -> bool:
    try:
        return bool(bot.in_pathing_grid(pos))
    except Exception:
        return True


def _safe(pos: Optional[Point2], fallback: Point2) -> Point2:
    if pos is None:
        return fallback
    return pos


def _main_wall_guard_points(bot) -> list[tuple[Point2, float]]:
    ramp = getattr(bot, "main_base_ramp", None)
    if ramp is None:
        return []
    out: list[tuple[Point2, float]] = []
    top = getattr(ramp, "top_center", None)
    bottom = getattr(ramp, "bottom_center", None)
    if top is not None:
        out.append((top, 7.5))
    if bottom is not None:
        out.append((bottom, 6.75))
    for depot in list(getattr(ramp, "corner_depots", []) or []):
        if depot is not None:
            out.append((depot, 4.25))
    barracks_pos = getattr(ramp, "barracks_correct_placement", None)
    if barracks_pos is not None:
        out.append((barracks_pos, 4.0))
    return out


def _respects_guard_points(pos: Point2 | None, guards: list[tuple[Point2, float]], *, slack: float = 0.15) -> bool:
    if pos is None:
        return False
    for guarded_point, min_dist in list(guards or []):
        try:
            if float(pos.distance_to(guarded_point)) + float(slack) < float(min_dist):
                return False
        except Exception:
            continue
    return True


class SectorGraph:
    """
    Calcula e cacheia as posições concretas dos setores operacionais.

    Deve ser recalculado raramente (a cada ~30s ou quando bases mudam).
    As posições são estáveis — o mapa não muda em tempo de jogo.
    """

    def __init__(self) -> None:
        self._positions: dict[SectorId, Point2] = {}
        self._computed: bool = False
        self._computed_bases: int = 0  # Número de bases quando foi computado

    def get(self, sector_id: SectorId) -> Optional[Point2]:
        return self._positions.get(sector_id)

    def compute(self, bot) -> None:
        """
        Calcula posições a partir do bot/mediator.

        Cache: posições do mapa são estáticas, mas alguns setores dependem
        de estado estrutural (nat, third entry). Recomputa quando o número
        de bases muda para capturar novas expansões.

        LIMITAÇÃO CONHECIDA: setores derivados de estado (offsite CC, third entry)
        não atualizam automaticamente quando a situação muda sem mudança de base_count.
        """
        current_bases = int(getattr(bot, "townhalls", None) and bot.townhalls.amount or 0)

        if self._computed and int(current_bases) == int(self._computed_bases):
            return
        try:
            self._do_compute(bot)
            self._computed = True
            self._computed_bases = int(current_bases)
        except Exception:
            pass  # Tenta novamente no próximo tick

    def _do_compute(self, bot) -> None:
        main = bot.start_location
        enemy_main = bot.enemy_start_locations[0] if bot.enemy_start_locations else main

        # Nat position
        nat: Optional[Point2] = None
        try:
            nat = bot.mediator.get_own_nat
        except Exception:
            pass
        if nat is None:
            exps = list(getattr(bot, "expansion_locations_list", []) or [])
            ordered = sorted(
                [p for p in exps if float(p.distance_to(main)) > 2.0],
                key=lambda p: float(main.distance_to(p)),
            )
            nat = ordered[0] if ordered else main

        # HOME_CORE
        self._positions[SectorId.HOME_CORE] = main

        # MAIN_RAMP
        ramp = getattr(bot, "main_base_ramp", None)
        ramp_top = None
        ramp_bottom = None
        if ramp is not None:
            ramp_top = getattr(ramp, "top_center", None)
            ramp_bottom = getattr(ramp, "bottom_center", None)
        guards = _main_wall_guard_points(bot)
        # Posição do setor MAIN_RAMP: recuada 7.5 tiles para dentro da main,
        # atrás da wall — tanks siegam aqui sem bloquear o corredor de saída para a nat.
        if ramp_top is not None:
            try:
                ramp_sector_pos = _safe(ramp_top.towards(main, 10.5), main)
            except Exception:
                ramp_sector_pos = main
            for backoff in (8.25, 9.0, 9.75, 10.5):
                try:
                    candidate = ramp_top.towards(main, backoff)
                except Exception:
                    candidate = ramp_top
                candidate = _safe(candidate, main)
                if _respects_guard_points(candidate, guards):
                    ramp_sector_pos = candidate
                    break
        else:
            ramp_sector_pos = main
        self._positions[SectorId.MAIN_RAMP] = ramp_sector_pos

        # NAT_FOOTPRINT
        self._positions[SectorId.NAT_FOOTPRINT] = nat

        # NAT_RING (entorno da nat — ligeiramente para o inimigo)
        nat_ring = nat.towards(enemy_main, 3.0)
        self._positions[SectorId.NAT_RING] = nat_ring

        # NAT_CHOKE — posição defensável na entrada da nat
        nat_choke = self._derive_nat_choke(bot, nat=nat, enemy_main=enemy_main)
        self._positions[SectorId.NAT_CHOKE] = nat_choke

        # RETREAT_BUFFER — entre ramp top e nat center
        ramp_anchor = _safe(ramp_top, main)
        retreat = ramp_anchor.towards(nat, 0.35)
        self._positions[SectorId.RETREAT_BUFFER] = retreat

        # MID_APPROACH — ~60% do caminho entre nat_choke e enemy_main
        mid_approach = nat_choke.towards(enemy_main, nat_choke.distance_to(enemy_main) * 0.35)
        if not _pathable(bot, mid_approach):
            mid_approach = nat_choke.towards(enemy_main, 5.0)
        self._positions[SectorId.MID_APPROACH] = mid_approach

        # WATCH_AREA — ~55% do caminho entre main e enemy_main
        watch = main.towards(enemy_main, main.distance_to(enemy_main) * 0.55)
        if not _pathable(bot, watch):
            watch = mid_approach
        self._positions[SectorId.WATCH_AREA] = watch

        # THIRD_ENTRY — terceira expansão, heurístico
        third = self._derive_third_entry(bot, main=main, nat=nat, enemy_main=enemy_main)
        self._positions[SectorId.THIRD_ENTRY] = _safe(third, nat)

        # PUSH_STAGING — entre nat_choke e mid, ponto de reunião antes de push
        push_staging = nat_choke.towards(enemy_main, nat_choke.distance_to(enemy_main) * 0.6)
        if not _pathable(bot, push_staging):
            push_staging = mid_approach
        self._positions[SectorId.PUSH_STAGING] = push_staging

    def _derive_nat_choke(self, bot, *, nat: Point2, enemy_main: Point2) -> Point2:
        """Posição defensável no choke da nat."""
        try:
            ramp = getattr(bot, "main_base_ramp", None)
            if ramp is not None:
                bottom = getattr(ramp, "bottom_center", None)
                if bottom is not None and float(bottom.distance_to(nat)) <= 20.0:
                    candidate = bottom.towards(enemy_main, 1.5)
                    if _pathable(bot, candidate):
                        return sanitize_natural_defense_point(
                            bot,
                            pos=candidate,
                            fallback=nat.towards(enemy_main, 5.5),
                            prefer_towards=nat.towards(enemy_main, 6.5),
                            nat=nat,
                        )
        except Exception:
            pass
        candidate = nat.towards(enemy_main, 5.5)
        if _pathable(bot, candidate):
            return sanitize_natural_defense_point(
                bot,
                pos=candidate,
                fallback=nat,
                prefer_towards=nat.towards(enemy_main, 6.5),
                nat=nat,
            )
        return nat

    def _derive_third_entry(
        self, bot, *, main: Point2, nat: Point2, enemy_main: Point2
    ) -> Optional[Point2]:
        """Terceira expansão — entrada lateral."""
        try:
            exps = list(getattr(bot, "expansion_locations_list", []) or [])
            # Pega expansões ordenadas por distância da nat, excluindo main e nat
            candidates = sorted(
                [
                    p for p in exps
                    if float(p.distance_to(main)) > 5.0 and float(p.distance_to(nat)) > 5.0
                ],
                key=lambda p: float(nat.distance_to(p)),
            )
            if candidates:
                third_base = candidates[0]
                # Entrada = ponto entre nat e third base
                entry = nat.towards(third_base, nat.distance_to(third_base) * 0.6)
                if _pathable(bot, entry):
                    return entry
                return third_base
        except Exception:
            pass
        return None

    def to_dict(self) -> dict[str, Optional[dict]]:
        """Serializa posições para awareness."""
        out = {}
        for sector_id, pos in self._positions.items():
            out[sector_id.value] = {"x": float(pos.x), "y": float(pos.y)}
        return out

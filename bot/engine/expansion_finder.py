#bot/engine/expansion_finder.py
from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from typing import Any, Dict, List, Optional, Tuple, Iterable

from sc2.position import Point2
from sc2.ids.unit_typeid import UnitTypeId as U


@dataclass(frozen=True)
class ExpansionRank:
    pos: Point2
    path_dist: float


def _k(p: Point2) -> Tuple[int, int]:
    # chave estável: coords *2 (grid de 0.5)
    return (int(round(float(p.x) * 2)), int(round(float(p.y) * 2)))


def _tile(p: Point2) -> Tuple[int, int]:
    # tile 1x1 (inteiro)
    return (int(round(float(p.x))), int(round(float(p.y))))


def _emit(logger: Any | None, event: str, payload: dict) -> None:
    if logger is None:
        return
    fn = getattr(logger, "emit", None)
    if callable(fn):
        try:
            fn(event, payload)
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Pathing helpers
# -----------------------------------------------------------------------------
def _in_pathing_grid(bot: Any, p: Point2) -> bool:
    fn = getattr(bot, "in_pathing_grid", None)
    if callable(fn):
        try:
            return bool(fn(p))
        except Exception:
            return False

    gi = getattr(bot, "game_info", None)
    grid = getattr(gi, "pathing_grid", None) if gi is not None else None
    if grid is None:
        return False

    x, y = _tile(p)
    try:
        return bool(grid[x, y])  # type: ignore[index]
    except Exception:
        try:
            return bool(grid.is_set(Point2((x, y))))  # type: ignore[attr-defined]
        except Exception:
            return False


def _nearest_pathable(bot: Any, p: Point2, *, max_r: int = 8) -> Optional[Point2]:
    """
    Ajusta p para um ponto caminhável no pathing_grid (ground).
    Se p já for válido, retorna p.
    Senão, procura um ponto próximo.
    """
    if p is None:
        return None
    p = Point2((float(p.x), float(p.y)))

    if _in_pathing_grid(bot, p):
        return p

    base_x, base_y = _tile(p)

    for r in range(1, int(max_r) + 1):
        for dx in range(-r, r + 1):
            for dy in (-r, r):
                q = Point2((base_x + dx, base_y + dy))
                if _in_pathing_grid(bot, q):
                    return q
        for dy in range(-r + 1, r):
            for dx in (-r, r):
                q = Point2((base_x + dx, base_y + dy))
                if _in_pathing_grid(bot, q):
                    return q

    return None


async def _query_path(bot: Any, a: Point2, b: Point2) -> Optional[float]:
    """
    Distância de chão entre a e b.
    - usa client.query_pathing
    - ajusta pontos para pathable
    - se falhar/None, retorna None (sem euclidiano)
    """
    client = getattr(bot, "client", None)
    if client is None:
        return None

    fn = getattr(client, "query_pathing", None)
    if not callable(fn):
        return None

    a2 = _nearest_pathable(bot, a)
    b2 = _nearest_pathable(bot, b)
    if a2 is None or b2 is None:
        return None

    try:
        d = await fn(a2, b2)
        if d is None:
            return None
        return float(d)
    except Exception:
        return None


def _grid_accessor(bot: Any):
    gi = getattr(bot, "game_info", None)
    grid = getattr(gi, "pathing_grid", None) if gi is not None else None
    if grid is None:
        return None

    w = getattr(grid, "width", None)
    h = getattr(grid, "height", None)
    if not isinstance(w, int) or not isinstance(h, int):
        size = getattr(grid, "size", None)
        if isinstance(size, tuple) and len(size) == 2:
            w, h = int(size[0]), int(size[1])

    if not isinstance(w, int) or not isinstance(h, int):
        return None

    def is_pathable(x: int, y: int) -> bool:
        if x < 0 or y < 0 or x >= w or y >= h:
            return False
        try:
            return bool(grid[x, y])  # type: ignore[index]
        except Exception:
            try:
                return bool(grid.is_set(Point2((x, y))))  # type: ignore[attr-defined]
            except Exception:
                return False

    return (w, h, is_pathable)


def _bfs_distances_on_pathing_grid(bot: Any, start: Point2) -> Optional[Dict[Tuple[int, int], int]]:
    """
    Fallback de chão (não-euclidiano):
    BFS no pathing_grid, custo uniforme por tile.
    """
    acc = _grid_accessor(bot)
    if acc is None:
        return None
    w, h, is_pathable = acc

    s = _nearest_pathable(bot, start)
    if s is None:
        return None

    sx, sy = _tile(s)
    if not is_pathable(sx, sy):
        return None

    dist: Dict[Tuple[int, int], int] = {}
    q = deque()
    dist[(sx, sy)] = 0
    q.append((sx, sy))

    while q:
        x, y = q.popleft()
        d0 = dist[(x, y)]
        nd = d0 + 1

        nx, ny = x + 1, y
        if (nx, ny) not in dist and is_pathable(nx, ny):
            dist[(nx, ny)] = nd
            q.append((nx, ny))

        nx, ny = x - 1, y
        if (nx, ny) not in dist and is_pathable(nx, ny):
            dist[(nx, ny)] = nd
            q.append((nx, ny))

        nx, ny = x, y + 1
        if (nx, ny) not in dist and is_pathable(nx, ny):
            dist[(nx, ny)] = nd
            q.append((nx, ny))

        nx, ny = x, y - 1
        if (nx, ny) not in dist and is_pathable(nx, ny):
            dist[(nx, ny)] = nd
            q.append((nx, ny))

    return dist


# -----------------------------------------------------------------------------
# Resource-based expansion discovery
# -----------------------------------------------------------------------------
def _iter_neutral_resources(bot: Any) -> List[Point2]:
    """
    Coleta posições de minerais + geysers do estado.
    Robusto a forks.
    """
    out: List[Point2] = []

    st = getattr(bot, "state", None)
    if st is None:
        return out

    minerals = getattr(st, "mineral_field", None)
    geysers = getattr(st, "vespene_geyser", None)

    try:
        if minerals is not None:
            for m in minerals:
                p = getattr(m, "position", None)
                if p is not None:
                    out.append(Point2((float(p.x), float(p.y))))
    except Exception:
        pass

    try:
        if geysers is not None:
            for g in geysers:
                p = getattr(g, "position", None)
                if p is not None:
                    out.append(Point2((float(p.x), float(p.y))))
    except Exception:
        pass

    return out


def _cluster_points(points: List[Point2], *, r: float = 9.0) -> List[List[Point2]]:
    """
    Clusterização simples (greedy) por raio.
    r=9 funciona bem para agrupar recursos de uma base.
    """
    clusters: List[List[Point2]] = []
    used = [False] * len(points)

    for i, p in enumerate(points):
        if used[i]:
            continue
        used[i] = True
        cl = [p]
        changed = True

        # expande enquanto achar pontos perto de qualquer do cluster
        while changed:
            changed = False
            for j, q in enumerate(points):
                if used[j]:
                    continue
                for a in cl:
                    if float(a.distance_to(q)) <= float(r):
                        used[j] = True
                        cl.append(q)
                        changed = True
                        break

        clusters.append(cl)

    return clusters


def _centroid(points: List[Point2]) -> Point2:
    x = sum(float(p.x) for p in points) / max(1, len(points))
    y = sum(float(p.y) for p in points) / max(1, len(points))
    return Point2((x, y))


async def _townhall_spot_near(bot: Any, near: Point2) -> Optional[Point2]:
    """
    Encontra um spot real de COMMANDCENTER perto do cluster.
    Isso reduz “expansão fantasma” e força spot buildável.
    """
    fn = getattr(bot, "find_placement", None)
    if not callable(fn):
        return near

    try:
        p = await fn(U.COMMANDCENTER, near=near, placement_step=2)
        if p is None:
            return None
        return Point2((float(p.x), float(p.y)))
    except Exception:
        return None


async def discover_expansions(bot: Any, *, logger: Any | None = None) -> List[Point2]:
    """
    Gera lista de expansões baseada em recursos (minerais/geysers).
    Fallback: game_info.expansion_locations_list.
    """
    resources = _iter_neutral_resources(bot)
    if resources:
        clusters = _cluster_points(resources, r=9.0)
        centers = [_centroid(c) for c in clusters]

        spots: List[Point2] = []
        seen: set[Tuple[int, int]] = set()

        for c in centers:
            p = await _townhall_spot_near(bot, c)
            if p is None:
                continue
            key = _k(p)
            if key in seen:
                continue
            seen.add(key)
            spots.append(p)

        if spots:
            _emit(logger, "expansion_discover_ok", {"count": len(spots)})
            return spots

    # fallback
    gi = getattr(bot, "game_info", None)
    ex = getattr(gi, "expansion_locations_list", None) if gi is not None else None
    out: List[Point2] = []
    try:
        if ex is not None:
            for p in ex:
                out.append(Point2((float(p.x), float(p.y))))
    except Exception:
        pass

    _emit(logger, "expansion_discover_fallback", {"count": len(out)})
    return out


# -----------------------------------------------------------------------------
# Ranking
# -----------------------------------------------------------------------------
async def rank_expansions_by_pathing(
    bot: Any,
    expansions: List[Point2],
    *,
    start: Point2,
    cache: Dict[Tuple[int, int], float] | None = None,
    bfs_fail_ratio: float = 0.5,
    logger: Any | None = None,
) -> List[ExpansionRank]:
    """
    Ordena expansões por distância de chão.
    - tenta query_pathing
    - se falhar muito, BFS no pathing_grid
    - nunca inventa euclidiano
    """
    cache = cache if cache is not None else {}

    ranks: List[ExpansionRank] = []
    missing: List[Point2] = []
    query_ok = 0
    query_fail = 0

    for p in expansions:
        key = _k(p)
        if key in cache:
            ranks.append(ExpansionRank(pos=p, path_dist=float(cache[key])))
            continue

        d = await _query_path(bot, start, p)
        if d is None:
            missing.append(p)
            query_fail += 1
            continue

        cache[key] = float(d)
        ranks.append(ExpansionRank(pos=p, path_dist=float(d)))
        query_ok += 1

    total = max(1, len(expansions))
    fail_ratio = float(len(missing)) / float(total)

    used_bfs = False
    if missing and fail_ratio >= float(bfs_fail_ratio):
        dist_map = _bfs_distances_on_pathing_grid(bot, start)
        if dist_map is not None:
            used_bfs = True
            for p in missing:
                tx, ty = _tile(p)
                steps = dist_map.get((tx, ty))
                if steps is None:
                    pp = _nearest_pathable(bot, p)
                    if pp is not None:
                        tx2, ty2 = _tile(pp)
                        steps = dist_map.get((tx2, ty2))

                if steps is None:
                    continue

                d2 = float(steps)
                cache[_k(p)] = d2
                ranks.append(ExpansionRank(pos=p, path_dist=d2))

    # para as que continuam sem dist, joga pra longe (mas SEM cache)
    for p in missing:
        if _k(p) in cache:
            continue
        ranks.append(ExpansionRank(pos=p, path_dist=1e18))

    ranks.sort(key=lambda r: r.path_dist)

    # log do ranking (top 8)
    _emit(
        logger,
        "expansion_ranked",
        {
            "start": [float(start.x), float(start.y)],
            "count": len(expansions),
            "query_ok": int(query_ok),
            "query_fail": int(query_fail),
            "used_bfs": bool(used_bfs),
            "top": [
                {"pos": [float(r.pos.x), float(r.pos.y)], "d": float(r.path_dist)}
                for r in ranks[:8]
            ],
        },
    )

    return ranks


# -----------------------------------------------------------------------------
# Main / Natural selection
# -----------------------------------------------------------------------------
def _default_anchor_my_main(bot: Any) -> Optional[Point2]:
    th = getattr(bot, "townhalls", None)
    try:
        if th is not None and th.ready:
            p = th.ready.first.position
            return Point2((float(p.x), float(p.y)))
    except Exception:
        pass
    p = getattr(bot, "start_location", None)
    if p is None:
        return None
    return Point2((float(p.x), float(p.y)))


def _default_anchor_enemy_main(bot: Any) -> Optional[Point2]:
    # 1) se já viu um townhall inimigo, usa isso (melhor do que start_location teórico)
    try:
        enemy_units = getattr(bot, "enemy_units", None)
        enemy_structures = getattr(bot, "enemy_structures", None)
        if callable(enemy_structures):
            for ut in (U.COMMANDCENTER, U.ORBITALCOMMAND, U.PLANETARYFORTRESS):
                es = enemy_structures(ut)
                if es and getattr(es, "ready", es).exists:
                    p = getattr(getattr(es, "ready", es).first, "position", None)
                    if p is not None:
                        return Point2((float(p.x), float(p.y)))
    except Exception:
        pass

    # 2) fallback: enemy_start_locations (1v1 -> [0])
    esl = getattr(bot, "enemy_start_locations", None)
    try:
        if esl and len(esl) >= 1:
            p = esl[0]
            return Point2((float(p.x), float(p.y)))
    except Exception:
        pass

    return None


async def compute_main_and_natural(
    bot: Any,
    *,
    expansions: List[Point2],
    start: Point2,
    cache: Dict[Tuple[int, int], float] | None = None,
    logger: Any | None = None,
) -> tuple[Optional[Point2], Optional[Point2]]:
    """
    Main = expansão mais próxima (ground) do start.
    Natural = próxima expansão com distância “suficiente” do main.

    Fix importante:
    - não usa cutoff ridículo (3.0). Usa thresholds mais realistas:
      * euclid_min = 7.0 (evita pocket/duplicata colada)
      * path_min  = 10.0 (evita ponto “do lado”)
    """
    if not expansions or start is None:
        return None, None

    ranks = await rank_expansions_by_pathing(
        bot,
        expansions,
        start=start,
        cache=cache,
        logger=logger,
    )

    if not ranks:
        return None, None

    main = ranks[0].pos

    # thresholds anti-pocket
    euclid_min = 7.0
    path_min = 10.0

    nat: Optional[Point2] = None
    for r in ranks[1:]:
        # garante que não é “colado” no main
        if float(r.pos.distance_to(main)) < euclid_min:
            continue
        # se tiver pathing real (não INF), exige também path_min
        if float(r.path_dist) < 1e17 and float(r.path_dist) < path_min:
            continue
        nat = r.pos
        break

    _emit(
        logger,
        "main_natural_chosen",
        {
            "start": [float(start.x), float(start.y)],
            "main": [float(main.x), float(main.y)] if main else None,
            "natural": [float(nat.x), float(nat.y)] if nat else None,
            "euclid_min": euclid_min,
            "path_min": path_min,
        },
    )

    return main, nat


# Convenience helpers (pra você usar no state/orchestrator)
async def compute_my_main_and_natural(
    bot: Any,
    *,
    cache: Dict[Tuple[int, int], float] | None = None,
    logger: Any | None = None,
) -> tuple[Optional[Point2], Optional[Point2]]:
    exps = await discover_expansions(bot, logger=logger)
    start = _default_anchor_my_main(bot)
    if start is None:
        return None, None
    return await compute_main_and_natural(bot, expansions=exps, start=start, cache=cache, logger=logger)


async def compute_enemy_main_and_natural(
    bot: Any,
    *,
    cache: Dict[Tuple[int, int], float] | None = None,
    logger: Any | None = None,
) -> tuple[Optional[Point2], Optional[Point2]]:
    exps = await discover_expansions(bot, logger=logger)
    start = _default_anchor_enemy_main(bot)
    if start is None:
        return None, None
    return await compute_main_and_natural(bot, expansions=exps, start=start, cache=cache, logger=logger)
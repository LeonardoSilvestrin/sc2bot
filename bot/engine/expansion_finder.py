#bot/engine/expansion_finder.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from sc2.position import Point2


@dataclass(frozen=True)
class ExpansionRank:
    pos: Point2
    path_dist: float


def _k(p: Point2) -> Tuple[int, int]:
    # chave estável: coords *2 (grid de 0.5)
    return (int(round(float(p.x) * 2)), int(round(float(p.y) * 2)))


async def _query_path(bot: Any, a: Point2, b: Point2) -> Optional[float]:
    """
    Retorna distância de pathing (aprox) entre a e b.
    Em python-sc2, normalmente: await bot.client.query_pathing(a, b)
    """
    client = getattr(bot, "client", None)
    if client is None:
        return None

    fn = getattr(client, "query_pathing", None)
    if not callable(fn):
        return None

    try:
        d = await fn(a, b)
        if d is None:
            return None
        return float(d)
    except Exception:
        return None


async def rank_expansions_by_pathing(
    bot: Any,
    expansions: List[Point2],
    *,
    start: Point2,
    cache: Dict[Tuple[int, int], float] | None = None,
) -> List[ExpansionRank]:
    """
    Ordena expansões por distância de pathing a partir de start.
    Cache por ponto (não por par) é suficiente aqui porque start é fixo (main).
    """
    cache = cache if cache is not None else {}

    ranks: List[ExpansionRank] = []
    for p in expansions:
        key = _k(p)
        if key in cache:
            ranks.append(ExpansionRank(pos=p, path_dist=float(cache[key])))
            continue

        d = await _query_path(bot, start, p)
        if d is None:
            # sem path: joga pra longe
            d = 1e18
        cache[key] = float(d)
        ranks.append(ExpansionRank(pos=p, path_dist=float(d)))

    ranks.sort(key=lambda r: r.path_dist)
    return ranks


async def compute_main_and_natural(
    bot: Any,
    *,
    expansions: List[Point2],
    start: Point2,
    cache: Dict[Tuple[int, int], float] | None = None,
) -> tuple[Optional[Point2], Optional[Point2]]:
    """
    Main = expansão mais próxima (pathing) do start.
    Natural = segunda mais próxima (pathing) que seja > um pequeno epsilon do main.
    """
    if not expansions:
        return None, None

    ranks = await rank_expansions_by_pathing(bot, expansions, start=start, cache=cache)

    main = ranks[0].pos if ranks else None
    nat = None
    if main is not None:
        for r in ranks[1:]:
            # evita pegar o mesmo ponto “colado”
            if float(r.pos.distance_to(main)) > 3.0:
                nat = r.pos
                break
    return main, nat
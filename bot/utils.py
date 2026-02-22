#utils.py
from __future__ import annotations

from typing import Any, Optional
from sc2.position import Point2

NEUTRAL_OWNER = 16


def snap(p: Point2) -> Point2:
    # snap para múltiplos de 0.5 (half-tile)
    x = round(p.x * 2) / 2
    y = round(p.y * 2) / 2
    return Point2((x, y))

def game_loop(bot: Any) -> int:
    """
    Best-effort game loop getter.
    - python-sc2: bot.state.game_loop exists.
    - fallback: approximate from bot.time seconds * 22.4 loops/s.
    """
    st = getattr(bot, "state", None)
    gl = getattr(st, "game_loop", None)
    if isinstance(gl, int):
        return gl
    t = getattr(bot, "time", 0.0)
    try:
        return int(float(t) * 22.4)
    except Exception:
        return 0


def raw_owner(u: Any) -> Optional[int]:
    p = getattr(u, "_proto", None)
    if p is None:
        v = getattr(u, "owner_id", None)
        return int(v) if v is not None else None
    v = getattr(p, "owner", None)
    return int(v) if v is not None else None


def name(u: Any) -> str:
    return str(getattr(u, "name", ""))
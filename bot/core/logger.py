from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _json_default(o: Any):
    # dataclass -> dict
    if is_dataclass(o):
        return asdict(o)
    # objetos comuns do python-sc2 que têm .name
    name = getattr(o, "name", None)
    if isinstance(name, str):
        return name
    # fallback
    return str(o)


class JsonlLogger:
    """
    Escreve eventos em JSON Lines (1 JSON por linha).
    - Não trava o bot: I/O mínimo, append.
    - Você pode abrir o arquivo enquanto o jogo roda.
    """

    def __init__(self, *, log_dir: str = "logs", filename: Optional[str] = None, enabled: bool = True):
        self.enabled = enabled
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        if filename is None:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"game_{ts}.jsonl"

        self.path = self.log_dir / filename
        self._fp = open(self.path, "a", encoding="utf-8")

    def close(self):
        try:
            self._fp.close()
        except Exception:
            pass

    def emit(self, event: str, payload: Dict[str, Any] | None = None, *, meta: Dict[str, Any] | None = None):
        if not self.enabled:
            return
        rec = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "payload": payload or {},
            "meta": meta or {},
        }
        self._fp.write(json.dumps(rec, ensure_ascii=False, default=_json_default) + "\n")
        self._fp.flush()
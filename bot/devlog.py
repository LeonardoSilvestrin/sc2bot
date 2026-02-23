#bot/devlog.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class DevLogger:
    """
    Logger JSONL simples (1 evento por linha).
    Objetivo: você conseguir auditar decisões ("flags") pós-partida.
    """

    log_dir: str = "logs"
    filename: Optional[str] = None
    enabled: bool = True

    def _ensure_dir(self) -> None:
        os.makedirs(self.log_dir, exist_ok=True)

    def set_file(self, filename: str) -> None:
        self.filename = filename

    def emit(self, event: str, payload: Optional[Dict[str, Any]] = None, *, meta: Optional[Dict[str, Any]] = None) -> None:
        if not self.enabled:
            return
        if not self.filename:
            # Se esquecer de setar, não explode o jogo.
            return

        self._ensure_dir()
        row = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "payload": payload or {},
            "meta": meta or {},
        }
        path = os.path.join(self.log_dir, self.filename)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            # logging nunca pode matar o bot
            pass
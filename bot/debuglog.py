#debuglog.py
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class _Run:
    run_dir: Path
    log_path: Path


class DebugLogger:
    """
    Single-file JSONL logger, buffered (não dá flush a cada linha).
    - Um arquivo: debug.jsonl
    - Compatível com suas chamadas atuais:
        log_action / log_state / log_placement / log_building
    - Nunca quebra o bot: exceções do logger são engolidas.
    """

    def __init__(
        self,
        base_dir: str | Path = "debug_runs",
        *,
        enabled: bool = True,
        flush_every_lines: int = 200,
        flush_every_seconds: float = 1.0,
        max_payload_bytes: int = 8_000,
    ):
        self.enabled = bool(enabled)
        self.base_dir = Path(base_dir)
        self.flush_every_lines = int(flush_every_lines)
        self.flush_every_seconds = float(flush_every_seconds)
        self.max_payload_bytes = int(max_payload_bytes)

        self._run: Optional[_Run] = None
        self._fp = None  # file handle
        self._lines_since_flush = 0
        self._last_flush_ts = 0.0

    # -------------------------
    # Lifecycle
    # -------------------------
    def start_run(self, *, map_name: str = "unknown_map", opponent: str = "unknown_opp") -> None:
        if not self.enabled:
            return

        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_map = "".join(c for c in map_name if c.isalnum() or c in ("_", "-"))[:48] or "map"
            safe_opp = "".join(c for c in opponent if c.isalnum() or c in ("_", "-"))[:48] or "opp"

            run_dir = self.base_dir / f"{ts}_{safe_map}_{safe_opp}"
            run_dir.mkdir(parents=True, exist_ok=True)

            log_path = run_dir / "debug.jsonl"
            # line-buffered off; we'll flush manually
            self._fp = log_path.open("a", encoding="utf-8")
            self._run = _Run(run_dir=run_dir, log_path=log_path)

            self._lines_since_flush = 0
            self._last_flush_ts = time.time()

            self.log("state", {"event": "run_start", "map": map_name, "opponent": opponent})
        except Exception:
            # never break the bot due to logging
            self._run = None
            try:
                if self._fp:
                    self._fp.close()
            except Exception:
                pass
            self._fp = None

    def close(self) -> None:
        """Call optionally in on_end; safe if never called."""
        try:
            if not self.enabled:
                return
            self._flush(force=True)
            if self._fp:
                self._fp.close()
        except Exception:
            pass
        finally:
            self._fp = None
            self._run = None

    # -------------------------
    # Public API
    # -------------------------
    def log(self, channel: str, obj: Dict[str, Any]) -> None:
        if not self.enabled or self._fp is None:
            return

        try:
            payload = dict(obj) if isinstance(obj, dict) else {"msg": str(obj)}
            payload.setdefault("channel", str(channel))

            s = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if len(s.encode("utf-8")) > self.max_payload_bytes:
                payload = self._shrink(payload)
                s = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

            self._fp.write(s + "\n")
            self._lines_since_flush += 1
            self._flush()
        except Exception:
            # swallow any logging failures
            return

    # Backward-compatible channels
    def log_action(self, obj: Dict[str, Any]) -> None:
        self.log("action", obj)

    def log_state(self, obj: Dict[str, Any]) -> None:
        self.log("state", obj)

    def log_placement(self, obj: Dict[str, Any]) -> None:
        self.log("placement", obj)

    def log_building(self, obj: Dict[str, Any]) -> None:
        self.log("building", obj)

    # -------------------------
    # Internals
    # -------------------------
    def _flush(self, *, force: bool = False) -> None:
        if self._fp is None:
            return

        now = time.time()
        if not force:
            if self._lines_since_flush < self.flush_every_lines and (now - self._last_flush_ts) < self.flush_every_seconds:
                return

        try:
            self._fp.flush()
        except Exception:
            return
        finally:
            self._lines_since_flush = 0
            self._last_flush_ts = now

    def _shrink(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Se o payload ficar grande demais, remove campos comuns que explodem (args/kwargs/result),
        mantendo os mais úteis para diagnóstico.
        """
        keep_keys = ("event", "fn", "what", "unit", "name", "ok", "reason", "exc_type", "exc", "t", "it", "channel")
        slim: Dict[str, Any] = {k: payload[k] for k in keep_keys if k in payload}

        # Preserve some positional hints if present
        for k in ("pos", "desired", "near", "cc"):
            if k in payload:
                slim[k] = payload[k]

        # If still nothing meaningful, keep a truncated repr
        if len(slim) <= 2:
            slim["event"] = payload.get("event", "log")
            slim["note"] = "payload_truncated"
            slim["repr"] = str(payload)[:400]

        return slim
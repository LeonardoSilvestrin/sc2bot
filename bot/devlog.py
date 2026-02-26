# bot/devlog.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class DevLogger:
    """
    JSONL logger (1 evento por linha).

    Estrutura de saida:
    - consolidado: logs/<filename>
    - por modulo: logs/<run_stem>/<module>.jsonl
    - ticks por modulo: logs/<run_stem>/ticks/<module>.jsonl
    """

    log_dir: str = "logs"
    filename: Optional[str] = None
    enabled: bool = True
    split_by_module: bool = True

    def _ensure_dir(self) -> None:
        os.makedirs(self.log_dir, exist_ok=True)

    def set_file(self, filename: str) -> None:
        self.filename = filename

    @staticmethod
    def _module_from_event(event: str, meta: Optional[Dict[str, Any]] = None) -> str:
        if isinstance(meta, dict):
            mod = meta.get("module")
            if isinstance(mod, str) and mod.strip():
                return mod.strip().lower()

        ev = str(event or "").strip().lower()
        if ev.startswith("macro_"):
            return "macro"
        if ev.startswith("defend_"):
            return "defense"
        if ev.startswith("reaper_") or ev.startswith("scout_") or ev.startswith("scan_") or ev.startswith("intel_"):
            return "intel"
        if ev.startswith("mission_"):
            return "ego"
        if ev.startswith("runtime_") or ev.startswith("game_"):
            return "runtime"
        return "misc"

    @staticmethod
    def _component_from_event(event: str, meta: Optional[Dict[str, Any]] = None) -> str:
        if isinstance(meta, dict):
            comp = meta.get("component")
            if isinstance(comp, str) and comp.strip():
                return comp.strip().lower()
        return DevLogger._module_from_event(event, meta)

    @staticmethod
    def _safe_stem(filename: str) -> str:
        stem, _ = os.path.splitext(str(filename))
        return stem or "devlog"

    @staticmethod
    def _write_jsonl(path: str, row: Dict[str, Any]) -> None:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def emit(
        self,
        event: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return
        if not self.filename:
            # Se esquecer de setar, nao explode o jogo.
            return

        self._ensure_dir()

        module = self._module_from_event(event, meta)
        component = self._component_from_event(event, meta)
        row = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "module": module,
            "component": component,
            "payload": payload or {},
            "meta": meta or {},
        }

        consolidated_path = os.path.join(self.log_dir, self.filename)
        try:
            # backward-compatible consolidated log
            self._write_jsonl(consolidated_path, row)

            if self.split_by_module:
                run_stem = self._safe_stem(self.filename)
                split_dir = os.path.join(self.log_dir, run_stem)
                os.makedirs(split_dir, exist_ok=True)

                module_path = os.path.join(split_dir, f"{module}.jsonl")
                self._write_jsonl(module_path, row)

                components_dir = os.path.join(split_dir, "components")
                os.makedirs(components_dir, exist_ok=True)
                safe_component = component.replace("/", "_").replace("\\", "_").replace(":", "_")
                component_path = os.path.join(components_dir, f"{safe_component}.jsonl")
                self._write_jsonl(component_path, row)

                if str(event).lower().endswith("_tick"):
                    ticks_dir = os.path.join(split_dir, "ticks")
                    os.makedirs(ticks_dir, exist_ok=True)
                    ticks_path = os.path.join(ticks_dir, f"{module}.jsonl")
                    self._write_jsonl(ticks_path, row)
        except Exception:
            # logging nunca pode matar o bot
            pass

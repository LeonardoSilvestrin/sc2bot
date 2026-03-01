from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# =========================
# Config
# =========================
# Arquivo hardcoded para abrir no main().
HARDCODED_LOG_PATH = Path(
    r"C:\Users\Asus\Documents\projetos\sc2bot\ares\ares-sc2-bot-template\logs\devlog_20260228_222931\components\awareness.snapshot.jsonl"
)

# Filtros (None/[] = sem filtro)
FILTER_EVENT_CONTAINS: Optional[str] = None
FILTER_EVENT_IN: List[str] = []  # ex: ["mission_started", "mission_ended"]
FILTER_COMPONENT_CONTAINS: Optional[str] = None  # meta__component
FILTER_MODULE_CONTAINS: Optional[str] = None  # meta__module
FILTER_MISSION_ID_CONTAINS: Optional[str] = None  # payload__mission_id
FILTER_REASON_CONTAINS: Optional[str] = None  # payload__reason
FILTER_ONLY_PARSE_ERRORS: bool = False
FILTER_T_GAME_MIN: Optional[float] = None
FILTER_T_GAME_MAX: Optional[float] = None

EXPORT_CSV_PATH: Optional[Path] = None


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    obj["_line"] = i
                    rows.append(obj)
                else:
                    rows.append({"_line": i, "_raw": line, "_parse_error": "non_dict_json"})
            except json.JSONDecodeError as e:
                rows.append({"_parse_error": str(e), "_line": i, "_raw": line})
    return rows


def _extract_game_time(payload: Any) -> Optional[float]:
    if not isinstance(payload, dict):
        return None
    t = payload.get("t")
    if isinstance(t, (int, float)):
        return float(t)
    t2 = payload.get("time")
    if isinstance(t2, (int, float)):
        return float(t2)
    return None


def build_dataframe(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    base: List[Dict[str, Any]] = []
    payload_list: List[Dict[str, Any]] = []
    meta_list: List[Dict[str, Any]] = []

    for r in rows:
        if not isinstance(r, dict):
            r = {"_raw": str(r), "_parse_error": "non_dict_row"}

        payload = r.get("payload", {})
        meta = r.get("meta", {})
        if not isinstance(payload, dict):
            payload = {"_non_dict_payload": str(payload)}
        if not isinstance(meta, dict):
            meta = {"_non_dict_meta": str(meta)}

        base.append(
            {
                "ts_utc": r.get("ts_utc"),
                "event": r.get("event"),
                "t_game": _extract_game_time(payload),
                "_line": r.get("_line"),
                "_has_parse_error": bool(r.get("_parse_error")),
                "_parse_error": r.get("_parse_error"),
                "_raw": r.get("_raw"),
                "payload_raw": r.get("payload", {}),
                "meta_raw": r.get("meta", {}),
            }
        )
        payload_list.append(payload)
        meta_list.append(meta)

    df_base = pd.DataFrame(base)
    df_payload = pd.json_normalize(payload_list).add_prefix("payload__")
    df_meta = pd.json_normalize(meta_list).add_prefix("meta__")
    df = pd.concat([df_base, df_payload, df_meta], axis=1)

    if "t_game" in df.columns:
        df = df.sort_values(by=["t_game", "ts_utc"], ascending=[True, True], na_position="last")
    return df.reset_index(drop=True)


def _contains(df: pd.DataFrame, col: str, needle: Optional[str]) -> pd.Series:
    if not needle:
        return pd.Series([True] * len(df), index=df.index)
    if col not in df.columns:
        return pd.Series([False] * len(df), index=df.index)
    return df[col].astype(str).str.lower().str.contains(str(needle).lower(), na=False)


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    mask = pd.Series([True] * len(df), index=df.index)
    mask &= _contains(df, "event", FILTER_EVENT_CONTAINS)
    mask &= _contains(df, "meta__component", FILTER_COMPONENT_CONTAINS)
    mask &= _contains(df, "meta__module", FILTER_MODULE_CONTAINS)
    mask &= _contains(df, "payload__mission_id", FILTER_MISSION_ID_CONTAINS)
    mask &= _contains(df, "payload__reason", FILTER_REASON_CONTAINS)

    if FILTER_EVENT_IN:
        allow = {str(x).strip() for x in FILTER_EVENT_IN if str(x).strip()}
        if allow:
            mask &= df["event"].astype(str).isin(allow)

    if FILTER_ONLY_PARSE_ERRORS:
        mask &= df["_has_parse_error"].astype(bool)

    if FILTER_T_GAME_MIN is not None:
        mask &= pd.to_numeric(df["t_game"], errors="coerce") >= float(FILTER_T_GAME_MIN)
    if FILTER_T_GAME_MAX is not None:
        mask &= pd.to_numeric(df["t_game"], errors="coerce") <= float(FILTER_T_GAME_MAX)

    return df[mask].reset_index(drop=True)


def summarize(df: pd.DataFrame, *, path: Path) -> None:
    print("\n================ SUMMARY ================")
    print(f"Path: {path}")
    print(f"Rows: {len(df)}")
    if "_has_parse_error" in df.columns and df["_has_parse_error"].any():
        print(f"Parse errors: {int(df['_has_parse_error'].sum())}")
    if "event" in df.columns and len(df) > 0:
        print("\nTop events:")
        print(df["event"].value_counts(dropna=False).head(20).to_string())
    if "t_game" in df.columns and df["t_game"].notna().any():
        tmin = float(df["t_game"].dropna().min())
        tmax = float(df["t_game"].dropna().max())
        print(f"\nGame time range: {tmin:.2f}s -> {tmax:.2f}s")
    payload_cols = [c for c in df.columns if c.startswith("payload__")]
    meta_cols = [c for c in df.columns if c.startswith("meta__")]
    print(f"\nColumns: total={len(df.columns)} payload={len(payload_cols)} meta={len(meta_cols)}")


def export_csv(df: pd.DataFrame, out: Path) -> None:
    df2 = df.copy()
    df2["payload_raw"] = df2["payload_raw"].apply(
        lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else str(x)
    )
    df2["meta_raw"] = df2["meta_raw"].apply(
        lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else str(x)
    )
    df2.to_csv(out, index=False, encoding="utf-8")
    print(f"\nCSV exported to: {out}")


def main() -> None:
    log_path = HARDCODED_LOG_PATH
    if not log_path.exists():
        raise SystemExit(f"File not found: {log_path}")

    rows = _read_jsonl(log_path)
    df = build_dataframe(rows)
    df = apply_filters(df)
    summarize(df, path=log_path)

    from pandasgui import show

    show(df)

    if EXPORT_CSV_PATH:
        export_csv(df, EXPORT_CSV_PATH)


if __name__ == "__main__":
    main()

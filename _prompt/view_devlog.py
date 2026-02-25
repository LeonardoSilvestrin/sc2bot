# scripts/view_devlog.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# =========================================================
# 🔧 CONFIGURE AQUI
# =========================================================
LOG_PATH = Path(
    r"C:\Users\Asus\Documents\projetos\sc2bot\ares\ares-sc2-bot-template\logs\MyBot__Persephone_AIE__vs__Protoss__start.jsonl"
)

# filtro opcional antes de abrir no pandasgui (None = sem filtro)
FILTER_EVENT_CONTAINS: Optional[str] = None  # ex: "defend", "scan", "task_"

# export opcional (None = não exporta)
EXPORT_CSV_PATH: Optional[Path] = None  # ex: Path("out.csv")
# =========================================================


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
    """
    Saída:
      - colunas base: ts_utc, event, t_game, _line, _has_parse_error, _parse_error, _raw
      - payload expandido: payload__*
      - meta expandido: meta__*
      - payload_raw/meta_raw preservados
    """
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
                # preserva original para auditoria
                "payload_raw": r.get("payload", {}),
                "meta_raw": r.get("meta", {}),
            }
        )
        payload_list.append(payload)
        meta_list.append(meta)

    df_base = pd.DataFrame(base)

    # explode payload/meta em colunas
    df_payload = pd.json_normalize(payload_list).add_prefix("payload__")
    df_meta = pd.json_normalize(meta_list).add_prefix("meta__")

    df = pd.concat([df_base, df_payload, df_meta], axis=1)

    # ordenação preferencial
    if "t_game" in df.columns:
        df = df.sort_values(
            by=["t_game", "ts_utc"],
            ascending=[True, True],
            na_position="last",
        )

    return df.reset_index(drop=True)


def summarize(df: pd.DataFrame) -> None:
    print("\n================ SUMMARY ================")
    print(f"Rows: {len(df)}")

    if df["_has_parse_error"].any():
        print(f"Parse errors: {int(df['_has_parse_error'].sum())}")

    print("\nTop events:")
    print(df["event"].value_counts(dropna=False).to_string())

    if df["t_game"].notna().any():
        tmin = float(df["t_game"].dropna().min())
        tmax = float(df["t_game"].dropna().max())
        print(f"\nGame time range: {tmin:.2f}s -> {tmax:.2f}s")

    # sanity: quantas colunas payload/meta geradas
    payload_cols = [c for c in df.columns if c.startswith("payload__")]
    meta_cols = [c for c in df.columns if c.startswith("meta__")]
    print(f"\nColumns: total={len(df.columns)} payload={len(payload_cols)} meta={len(meta_cols)}")


def maybe_filter(df: pd.DataFrame, contains: Optional[str]) -> pd.DataFrame:
    if not contains:
        return df
    c = contains.lower()
    return df[df["event"].astype(str).str.lower().str.contains(c, na=False)].reset_index(drop=True)


def export_csv(df: pd.DataFrame, out: Path) -> None:
    df2 = df.copy()

    # payload_raw/meta_raw podem ser dict/list; serializa pra csv ficar estável
    df2["payload_raw"] = df2["payload_raw"].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else str(x))
    df2["meta_raw"] = df2["meta_raw"].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, (dict, list)) else str(x))

    df2.to_csv(out, index=False, encoding="utf-8")
    print(f"\nCSV exported to: {out}")


def main() -> None:
    if not LOG_PATH.exists():
        raise SystemExit(f"File not found: {LOG_PATH}")

    rows = _read_jsonl(LOG_PATH)
    df = build_dataframe(rows)
    df = maybe_filter(df, FILTER_EVENT_CONTAINS)

    summarize(df)

    # abre no pandasgui
    from pandasgui import show  # lazy import

    show(df)

    if EXPORT_CSV_PATH:
        export_csv(df, EXPORT_CSV_PATH)


if __name__ == "__main__":
    main()
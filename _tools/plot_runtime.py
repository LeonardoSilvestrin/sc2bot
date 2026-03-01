from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            out.append(json.loads(s))
        except Exception:
            continue
    return out


def _latest_run(logs_dir: Path) -> Path:
    runs = [p for p in logs_dir.iterdir() if p.is_dir() and p.name.startswith("devlog_")]
    if not runs:
        raise RuntimeError(f"no devlog_* directories in {logs_dir}")
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0]


def _xy(rows: list[dict[str, Any]], event: str, key: str) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for r in rows:
        if str(r.get("event", "")) != event:
            continue
        payload = r.get("payload", {}) or {}
        try:
            t = float(payload.get("t"))
            v = float(payload.get(key))
        except Exception:
            continue
        xs.append(t)
        ys.append(v)
    return xs, ys


def main() -> None:
    ap = argparse.ArgumentParser(description="Plot SC2 bot runtime + PID signals from dev logs.")
    ap.add_argument("--logs-dir", default="logs", help="Directory containing devlog_* runs.")
    ap.add_argument("--run", default="", help="Run directory name (e.g. devlog_20260301_213022).")
    ap.add_argument("--out-dir", default="_tools/out", help="Output directory root for generated PNG.")
    args = ap.parse_args()

    logs_dir = Path(args.logs_dir)
    if not logs_dir.exists():
        raise RuntimeError(f"logs dir not found: {logs_dir}")

    run_dir = (logs_dir / args.run) if args.run else _latest_run(logs_dir)
    comp_dir = run_dir / "components"
    if not comp_dir.exists():
        raise RuntimeError(f"components dir not found: {comp_dir}")

    runtime_clock = _load_jsonl(comp_dir / "runtime.clock.jsonl")
    runtime_perf = _load_jsonl(comp_dir / "runtime.perf.jsonl")
    runtime_state = _load_jsonl(comp_dir / "runtime.state_snapshot.jsonl")

    try:
        import matplotlib.pyplot as plt
    except Exception as e:
        raise RuntimeError("matplotlib is required. Install with: pip install matplotlib") from e

    out_dir = Path(args.out_dir) / run_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) speed + pid from runtime.clock
    fig, ax = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    x, y = _xy(runtime_clock, "runtime_clock", "speed_x")
    if x:
        ax[0].plot(x, y, label="speed_x")
        ax[0].set_ylabel("Speed (x)")
        ax[0].grid(True, alpha=0.25)
        ax[0].legend(loc="best")
    xp, yp = _xy(runtime_clock, "runtime_clock", "lag_production")
    xs, ys = _xy(runtime_clock, "runtime_clock", "lag_spending")
    xt, yt = _xy(runtime_clock, "runtime_clock", "lag_tech")
    xb, yb = _xy(runtime_clock, "runtime_clock", "bank_pi_output")
    if xp:
        ax[1].plot(xp, yp, label="lag_production")
    if xs:
        ax[1].plot(xs, ys, label="lag_spending")
    if xt:
        ax[1].plot(xt, yt, label="lag_tech")
    if xb:
        ax[1].plot(xb, yb, label="bank_pi_output")
    ax[1].set_xlabel("Game time (s)")
    ax[1].set_ylabel("PID / lag")
    ax[1].grid(True, alpha=0.25)
    ax[1].legend(loc="best")
    fig.suptitle(f"{run_dir.name} - Runtime Clock + PID")
    fig.tight_layout()
    fig.savefig(out_dir / "01_runtime_clock_pid.png", dpi=140)
    plt.close(fig)

    # 2) perf snapshot
    fig, ax = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    t, on_step = _xy(runtime_perf, "perf_snapshot", "on_step_total_ms")
    _, ego = _xy(runtime_perf, "perf_snapshot", "ego_ms")
    _, att = _xy(runtime_perf, "perf_snapshot", "attention_ms")
    _, facts = _xy(runtime_perf, "perf_snapshot", "awareness_facts")
    if t:
        ax[0].plot(t, on_step, label="on_step_total_ms")
        if ego:
            ax[0].plot(t, ego, label="ego_ms")
        if att:
            ax[0].plot(t, att, label="attention_ms")
        ax[0].set_ylabel("ms")
        ax[0].grid(True, alpha=0.25)
        ax[0].legend(loc="best")
        if facts:
            ax[1].plot(t, facts, label="awareness_facts")
            ax[1].set_ylabel("facts")
            ax[1].grid(True, alpha=0.25)
            ax[1].legend(loc="best")
    ax[1].set_xlabel("Game time (s)")
    fig.suptitle(f"{run_dir.name} - Perf")
    fig.tight_layout()
    fig.savefig(out_dir / "02_runtime_perf.png", dpi=140)
    plt.close(fig)

    # 3) economy + reserve block from state snapshot
    fig, ax = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    st: list[float] = []
    minerals: list[float] = []
    gas: list[float] = []
    supply_used: list[float] = []
    block_prod: list[float] = []
    for r in runtime_state:
        if str(r.get("event", "")) != "state_snapshot":
            continue
        p = r.get("payload", {}) or {}
        eco = p.get("economy", {}) or {}
        ctl = p.get("control", {}) or {}
        try:
            t0 = float(p.get("t"))
        except Exception:
            continue
        st.append(t0)
        minerals.append(float(eco.get("minerals", 0) or 0))
        gas.append(float(eco.get("gas", 0) or 0))
        supply_used.append(float(eco.get("supply_used", 0) or 0))
        block_prod.append(1.0 if bool(ctl.get("reserve_spending_block_production", False)) else 0.0)
    if st:
        ax[0].plot(st, minerals, label="minerals")
        ax[0].plot(st, gas, label="gas")
        ax[0].plot(st, supply_used, label="supply_used")
        ax[0].set_ylabel("value")
        ax[0].grid(True, alpha=0.25)
        ax[0].legend(loc="best")
        ax[1].step(st, block_prod, where="post", label="reserve_spending_block_production")
        ax[1].set_ylim(-0.1, 1.1)
        ax[1].set_ylabel("block")
        ax[1].set_xlabel("Game time (s)")
        ax[1].grid(True, alpha=0.25)
        ax[1].legend(loc="best")
    fig.suptitle(f"{run_dir.name} - Economy + Reserve Block")
    fig.tight_layout()
    fig.savefig(out_dir / "03_economy_reserves.png", dpi=140)
    plt.close(fig)

    print(f"run: {run_dir}")
    print(f"output: {out_dir}")
    for p in sorted(out_dir.glob("*.png")):
        print(f" - {p.name}")


if __name__ == "__main__":
    main()


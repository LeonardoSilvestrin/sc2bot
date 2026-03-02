from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "bot"

BANNED = (
    "from bot.planners.proposals import",
    "import bot.planners.proposals",
)


def main() -> int:
    bad: list[str] = []
    for p in TARGET.rglob("*.py"):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if any(tok in line for tok in BANNED):
                bad.append(f"{p.relative_to(ROOT)}:{i}: {line.strip()}")
    if bad:
        print("Found legacy imports:")
        for row in bad:
            print(row)
        return 1
    print("OK: no legacy bot.planners.proposals imports found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

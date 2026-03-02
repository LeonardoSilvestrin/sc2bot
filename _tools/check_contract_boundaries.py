from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = (ROOT / "bot" / "planners", ROOT / "bot" / "tasks")

# Contract rule: planners/tasks must consume intel only via Awareness/Attention.
IMPORT_INTEL_RE = re.compile(r"^\s*(from|import)\s+bot\.intel(?:\.|\b)", re.MULTILINE)
CALL_DERIVE_INTEL_RE = re.compile(r"\bderive_[A-Za-z0-9_]*intel\s*\(")


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for base in SCAN_DIRS:
        if not base.exists():
            continue
        out.extend(sorted(base.rglob("*.py")))
    return out


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def check_no_direct_intel_usage() -> list[str]:
    violations: list[str] = []
    for path in _iter_py_files():
        text = path.read_text(encoding="utf-8")
        if IMPORT_INTEL_RE.search(text):
            violations.append(f"{_rel(path)}: direct intel import is forbidden")
        if CALL_DERIVE_INTEL_RE.search(text):
            violations.append(f"{_rel(path)}: direct derive_*intel(...) call is forbidden")
    return violations


def main() -> int:
    violations = check_no_direct_intel_usage()
    if violations:
        print("[contract-check] FAIL")
        for v in violations:
            print(f" - {v}")
        return 1
    print("[contract-check] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

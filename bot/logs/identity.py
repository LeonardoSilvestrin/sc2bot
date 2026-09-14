"""Who a run is: its code and its decision-critical configuration.

Recorded once, in ``game.started``, so every decision in a log can be tied
back to the code and numbers that produced it. ``describe_build`` reads git's
own files (no subprocess) and reports no commit without a repository.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def canonical(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite configuration value {value!r}")
        return value
    if isinstance(value, Enum):
        return f"{type(value).__name__}.{value.name}"
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: canonical(getattr(value, item.name)) for item in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(canonical(key)): canonical(item) for key, item in value.items()}
    if isinstance(value, set | frozenset):
        return sorted((canonical(item) for item in value), key=_dump)
    if isinstance(value, tuple | list):
        return [canonical(item) for item in value]
    raise TypeError(f"cannot canonicalize a value of type {type(value).__name__}")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(_dump(canonical(value)).encode("utf-8")).hexdigest()[:16]


def describe_build(root: Path = REPOSITORY_ROOT) -> dict[str, str | None]:
    try:
        git = root / ".git"
        if git.is_file():
            text = git.read_text(encoding="utf-8").strip()
            git = (root / text.removeprefix("gitdir:").strip()).resolve()
        if not git.is_dir():
            return {"commit": None, "branch": None}
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return {"commit": head or None, "branch": None}
        ref = head.removeprefix("ref:").strip()
        common = git
        pointer = git / "commondir"
        if pointer.is_file():
            common = (git / pointer.read_text(encoding="utf-8").strip()).resolve()
        for directory in dict.fromkeys((git, common)):
            loose = directory / ref
            if loose.is_file():
                return {
                    "commit": loose.read_text(encoding="utf-8").strip(),
                    "branch": ref.removeprefix("refs/heads/"),
                }
            packed = directory / "packed-refs"
            if packed.is_file():
                for line in packed.read_text(encoding="utf-8").splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1] == ref:
                        return {"commit": parts[0], "branch": ref.removeprefix("refs/heads/")}
        return {"commit": None, "branch": ref.removeprefix("refs/heads/")}
    except (OSError, UnicodeDecodeError):
        return {"commit": None, "branch": None}


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

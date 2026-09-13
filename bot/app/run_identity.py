"""Who a run is: its code, its decision-critical configuration, its seed.

Recorded once, in ``game.started``, so every decision in a game's log can be
tied back to the exact code and numbers that produced it. Everything here is
pure except ``describe_build``, which reads git's own files (no subprocess)
and reports no commit when there is no repository, as on the ladder.
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
    """``value`` as plain JSON data with a deterministic shape.

    Dataclasses become field maps, enums ``Type.NAME``, sets sorted lists,
    tuples lists. Anything else raises: a configuration value that cannot be
    written exactly must not be fingerprinted approximately.
    """

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
            item.name: canonical(getattr(value, item.name))
            for item in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(canonical(key)): canonical(item) for key, item in value.items()}
    if isinstance(value, set | frozenset):
        return sorted((canonical(item) for item in value), key=_dump)
    if isinstance(value, tuple | list):
        return [canonical(item) for item in value]
    raise TypeError(
        f"cannot canonicalize a configuration value of type {type(value).__name__}"
    )


def fingerprint(value: Any) -> str:
    """A short, stable digest of ``value``'s canonical form."""

    return hashlib.sha256(_dump(canonical(value)).encode("utf-8")).hexdigest()[:16]


@dataclasses.dataclass(frozen=True, slots=True)
class BuildIdentity:
    """The code a run was built from, as far as the files can tell."""

    commit: str | None
    branch: str | None

    def log_fields(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "branch": self.branch,
            "source": "unknown" if self.commit is None else "git",
        }


UNKNOWN_BUILD = BuildIdentity(commit=None, branch=None)


def describe_build(root: Path = REPOSITORY_ROOT) -> BuildIdentity:
    """The checked-out commit and branch of the repository at ``root``.

    Follows a worktree's ``.git`` file and packed refs. Uncommitted changes
    are not detected. Returns ``UNKNOWN_BUILD`` for anything it cannot read.
    """

    try:
        git_dir = _git_dir(root)
        if git_dir is None:
            return UNKNOWN_BUILD
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return BuildIdentity(commit=head or None, branch=None)
        ref = head.removeprefix("ref:").strip()
        branch = ref.removeprefix("refs/heads/")
        common = _common_dir(git_dir)
        for directory in dict.fromkeys((git_dir, common)):
            commit = _read_ref(directory, ref)
            if commit is not None:
                return BuildIdentity(commit=commit, branch=branch)
        return BuildIdentity(commit=None, branch=branch)
    except (OSError, UnicodeDecodeError):
        return UNKNOWN_BUILD


def _git_dir(root: Path) -> Path | None:
    git = root / ".git"
    if git.is_dir():
        return git
    if git.is_file():
        text = git.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            return (root / text.removeprefix("gitdir:").strip()).resolve()
    return None


def _common_dir(git_dir: Path) -> Path:
    pointer = git_dir / "commondir"
    if pointer.is_file():
        return (git_dir / pointer.read_text(encoding="utf-8").strip()).resolve()
    return git_dir


def _read_ref(git_dir: Path, ref: str) -> str | None:
    loose = git_dir / ref
    if loose.is_file():
        return loose.read_text(encoding="utf-8").strip() or None
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref:
                return parts[0]
    return None


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


__all__ = [
    "REPOSITORY_ROOT",
    "UNKNOWN_BUILD",
    "BuildIdentity",
    "canonical",
    "describe_build",
    "fingerprint",
]

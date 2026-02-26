# _prompt/export_prompt_root.py
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Tuple

# -----------------------------------------------------------------------------
# Hardcoded bot export policy (edit this block)
# True  => include full file content for this folder
# False => include only folder/file structure (no file content)
# -----------------------------------------------------------------------------
BOT_FOLDER_POLICY: Dict[str, bool] = {
    "bot/ares_wrapper": True,
    "bot/intel": True,
    "bot/mind": True,
    "bot/planners": True,
    "bot/sensors": True,
    "bot/tasks": True,
}

# top-level files directly under bot/ (e.g. bot/main.py, bot/devlog.py)
BOT_TOP_LEVEL_FILES_FULL: bool = True

DEFAULT_EXCLUDE_DIRS: Set[str] = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    ".idea",
    ".vscode",
    ".vscode1",
    "ares-sc2",
    "data",
}

ROOT_FILES: List[str] = [
    "terran_builds.yml",
    "config.yml",
    "run.py",
    "ARCHITECTURE.md",
]


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def normalize_rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def parse_csv(value: str) -> List[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def resolve_repo_root(cli_root: str | None) -> Path:
    if cli_root:
        return Path(cli_root).resolve()
    return Path(__file__).resolve().parent.parent


def is_excluded(path: Path, *, root: Path, exclude_dirs: Set[str]) -> bool:
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part in exclude_dirs for part in rel_parts)


def read_text_file(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def code_lang_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".py":
        return "python"
    if ext in {".yml", ".yaml"}:
        return "yaml"
    if ext == ".md":
        return "markdown"
    return ""


def build_tree(root: Path, *, exclude_dirs: Set[str], max_depth: int) -> str:
    lines: List[str] = ["."]

    def children_of(dir_path: Path) -> List[Path]:
        kids = [
            p
            for p in dir_path.iterdir()
            if p.name not in exclude_dirs and not (p.name.startswith("export_root_dump") and p.suffix == ".txt")
        ]
        kids.sort(key=lambda p: (0 if p.is_dir() else 1, p.name.lower()))
        return kids

    def walk(dir_path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        kids = children_of(dir_path)
        for i, child in enumerate(kids):
            last = i == len(kids) - 1
            branch = "`-- " if last else "|-- "
            lines.append(prefix + branch + child.name)
            if child.is_dir() and depth < max_depth:
                next_prefix = prefix + ("    " if last else "|   ")
                walk(child, next_prefix, depth + 1)

    walk(root, "", 1)
    return "\n".join(lines) + "\n"


def read_root_prompt_text(repo_root: Path) -> str:
    p = repo_root / "_prompt" / "root.txt"
    if not p.exists():
        return ""
    txt = read_text_file(p)
    return txt if txt.endswith("\n") else txt + "\n"


def summarize_latest_devlog(repo_root: Path, *, max_events: int) -> str:
    logs_dir = repo_root / "logs"
    if not logs_dir.exists():
        return "(logs/ not found)\n"

    candidates = sorted(
        [p for p in logs_dir.glob("devlog_*.jsonl") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return "(no devlog_*.jsonl found)\n"

    target = candidates[0]
    rows: List[dict] = []
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue

    from collections import Counter

    c = Counter(r.get("event") for r in rows)
    lines = [
        f"file: {target.name}",
        f"events_total: {len(rows)}",
        "top_events:",
    ]
    for name, count in c.most_common(12):
        lines.append(f"- {name}: {count}")

    lines.append("recent_events:")
    for r in rows[-max_events:]:
        lines.append(f"- {r.get('ts_utc', '')} {r.get('event', '')} {r.get('payload', {})}")

    return "\n".join(lines) + "\n"


def gather_python_files_under(root: Path, folder_rel: str, *, exclude_dirs: Set[str]) -> List[Path]:
    folder = (root / folder_rel).resolve()
    if not folder.exists() or not folder.is_dir():
        return []
    files = [p for p in folder.rglob("*.py") if p.is_file()]
    files = [p for p in files if not is_excluded(p, root=root, exclude_dirs=exclude_dirs)]
    files.sort(key=lambda p: normalize_rel(p, root).lower())
    return files


def gather_bot_top_level_py(root: Path, *, exclude_dirs: Set[str]) -> List[Path]:
    bot = root / "bot"
    if not bot.exists() or not bot.is_dir():
        return []
    files = [p for p in bot.glob("*.py") if p.is_file()]
    files = [p for p in files if not is_excluded(p, root=root, exclude_dirs=exclude_dirs)]
    files.sort(key=lambda p: normalize_rel(p, root).lower())
    return files


def render_file_block(path: Path, *, root: Path) -> str:
    rel = normalize_rel(path, root)
    text = read_text_file(path)
    if not text.endswith("\n"):
        text += "\n"
    return f"# {rel}\n```{code_lang_for(path)}\n{text}```\n"


def render_structure_only(folder_rel: str, files: List[Path], *, root: Path) -> str:
    lines = [f"## {folder_rel} (structure-only)"]
    if not files:
        lines.append("(no .py files found)")
    else:
        for p in files:
            lines.append(f"- {normalize_rel(p, root)}")
    return "\n".join(lines) + "\n\n"


def write_dump(
    *,
    repo_root: Path,
    out_path: Path,
    exclude_dirs: Set[str],
    include_root_prompt: bool,
    include_tree: bool,
    tree_max_depth: int,
    include_root_files: bool,
    include_log_summary: bool,
    log_events: int,
) -> None:
    parts: List[str] = []

    parts.append("===== EXPORT META =====\n")
    parts.append(f"generated_at_utc: {datetime.now(timezone.utc).isoformat()}\n")
    parts.append(f"repo_root: {repo_root}\n")
    parts.append("hardcoded_bot_policy:\n")
    for folder, full in BOT_FOLDER_POLICY.items():
        parts.append(f"- {folder}: {'FULL' if full else 'STRUCTURE_ONLY'}\n")
    parts.append(f"- bot/<top-level *.py>: {'FULL' if BOT_TOP_LEVEL_FILES_FULL else 'STRUCTURE_ONLY'}\n")
    parts.append("\n")

    if include_root_prompt:
        root_prompt = read_root_prompt_text(repo_root)
        if root_prompt:
            parts.append("===== ROOT PROMPT =====\n")
            parts.append(root_prompt)
            parts.append("\n")

    if include_tree:
        parts.append("===== PROJECT TREE =====\n")
        parts.append(build_tree(repo_root, exclude_dirs=exclude_dirs, max_depth=tree_max_depth))
        parts.append("\n")

    parts.append("===== BOT SNAPSHOT =====\n")

    # top-level bot files
    top_level_files = gather_bot_top_level_py(repo_root, exclude_dirs=exclude_dirs)
    if BOT_TOP_LEVEL_FILES_FULL:
        parts.append("## bot/<top-level *.py> (full)\n")
        for p in top_level_files:
            parts.append(render_file_block(p, root=repo_root))
    else:
        parts.append(render_structure_only("bot/<top-level *.py>", top_level_files, root=repo_root))

    # configured bot folders
    for folder_rel, include_full in BOT_FOLDER_POLICY.items():
        files = gather_python_files_under(repo_root, folder_rel, exclude_dirs=exclude_dirs)
        if include_full:
            parts.append(f"## {folder_rel} (full)\n")
            for p in files:
                parts.append(render_file_block(p, root=repo_root))
        else:
            parts.append(render_structure_only(folder_rel, files, root=repo_root))

    if include_root_files:
        parts.append("\n===== ROOT CONFIGS =====\n")
        for rel in ROOT_FILES:
            p = (repo_root / rel).resolve()
            if not p.exists() or not p.is_file():
                parts.append(f"# {rel}\n(not found)\n\n")
                continue
            if is_excluded(p, root=repo_root, exclude_dirs=exclude_dirs):
                continue
            parts.append(render_file_block(p, root=repo_root))

    if include_log_summary:
        parts.append("\n===== LOG SUMMARY =====\n")
        parts.append(summarize_latest_devlog(repo_root, max_events=log_events))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exporta contexto para revisao por outro agente (hardcoded bot folders, sem truncamento)."
    )
    parser.add_argument("--root", type=str, default=None)
    parser.add_argument("--out", type=str, default="export_root_dump.txt")
    parser.add_argument("--exclude-dirs", type=str, default=",".join(sorted(DEFAULT_EXCLUDE_DIRS)))
    parser.add_argument("--tree-max-depth", type=int, default=7)
    parser.add_argument("--log-events", type=int, default=50)

    parser.add_argument("--no-root-prompt", action="store_true")
    parser.add_argument("--no-tree", action="store_true")
    parser.add_argument("--no-root-files", action="store_true")
    parser.add_argument("--log-summary", action="store_true")

    args = parser.parse_args()

    repo_root = resolve_repo_root(args.root)

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = (repo_root / "_prompt" / out_path).resolve()

    exclude_dirs = set(parse_csv(args.exclude_dirs))

    write_dump(
        repo_root=repo_root,
        out_path=out_path,
        exclude_dirs=exclude_dirs,
        include_root_prompt=not args.no_root_prompt,
        include_tree=not args.no_tree,
        tree_max_depth=max(1, int(args.tree_max_depth)),
        include_root_files=not args.no_root_files,
        include_log_summary=bool(args.log_summary),
        log_events=max(1, int(args.log_events)),
    )

    print(f"OK: dump generated at {out_path}")


if __name__ == "__main__":
    main()

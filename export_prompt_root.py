# export_prompt_root.py
from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple


DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "logs",
    "sc2",  # você pode tirar se quiser incluir seu fork/lib local
    "dist",
    "build",
}

DEFAULT_EXCLUDE_GLOBS = {
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.so",
    "*.dll",
    "*.exe",
    "*.bin",
    "*.zip",
    "*.7z",
    "*.tar",
    "*.gz",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.webp",
    "*.mp4",
    "*.mov",
    "*.pdf",
}


# Heurística básica (não perfeita) pra evitar vazar segredos
SECRET_PATTERNS = [
    # KEY=..., TOKEN:..., etc.
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|bearer)\b\s*[:=]\s*([^\s'\"\\]+)"), r"\1=<REDACTED>"),
    # "Authorization: Bearer xxxxx"
    (re.compile(r"(?i)(Authorization\s*:\s*Bearer\s+)([A-Za-z0-9\-\._~\+\/]+=*)"), r"\1<REDACTED>"),
    # strings longas que parecem token
    (re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_\-]{32,}(?![A-Za-z0-9])"), "<REDACTED_LONG_TOKEN>"),
]


@dataclass(frozen=True)
class FileEntry:
    rel_path: str
    abs_path: Path


def _is_excluded_dir(dir_name: str, exclude_dirs: set[str]) -> bool:
    return dir_name in exclude_dirs


def _matches_any_glob(path: Path, globs: set[str]) -> bool:
    name = path.name
    for g in globs:
        if path.match(g) or Path(name).match(g):
            return True
    return False


def build_tree(root: Path, include_paths: List[Path], exclude_dirs: set[str]) -> str:
    """
    Gera uma tree simples só dos includes (bot/ + run.py por default).
    """
    # Normaliza para relativos
    rels = sorted({str(p.relative_to(root)).replace("\\", "/") for p in include_paths})
    # Monta estrutura
    tree = {}
    for r in rels:
        parts = r.split("/")
        cur = tree
        for part in parts:
            cur = cur.setdefault(part, {})

    def render(node: dict, prefix: str = "") -> List[str]:
        lines: List[str] = []
        items = list(node.items())
        for i, (name, child) in enumerate(items):
            last = i == len(items) - 1
            branch = "└── " if last else "├── "
            lines.append(prefix + branch + name)
            if child:
                extension = "    " if last else "│   "
                lines.extend(render(child, prefix + extension))
        return lines

    out = ["# Project tree (export)", "."]
    out.extend(render(tree))
    return "\n".join(out) + "\n"


def collect_files(root: Path, *, include_bot: bool, include_run: bool, extra: List[str],
                  exclude_dirs: set[str], exclude_globs: set[str]) -> List[FileEntry]:
    files: List[FileEntry] = []

    def add_file(p: Path):
        if not p.exists() or not p.is_file():
            return
        if _matches_any_glob(p, exclude_globs):
            return
        rel = str(p.relative_to(root)).replace("\\", "/")
        files.append(FileEntry(rel_path=rel, abs_path=p))

    if include_bot:
        bot_dir = root / "bot"
        if bot_dir.exists():
            for dirpath, dirnames, filenames in os.walk(bot_dir):
                # filtra dirs in-place
                dirnames[:] = [d for d in dirnames if not _is_excluded_dir(d, exclude_dirs)]
                for fn in filenames:
                    p = Path(dirpath) / fn
                    if _matches_any_glob(p, exclude_globs):
                        continue
                    # Só texto (principalmente .py, .json, .md, .txt, .yml)
                    if p.suffix.lower() in {".py", ".json", ".md", ".txt", ".yml", ".yaml"}:
                        add_file(p)

    if include_run:
        add_file(root / "run.py")

    for e in extra:
        add_file(root / e)

    # ordena estável
    files.sort(key=lambda x: x.rel_path)
    return files


def read_text(p: Path) -> str:
    # tenta utf-8-sig (bom pra JSON com BOM)
    try:
        return p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return p.read_text(encoding="utf-8", errors="replace")


def redact(text: str) -> str:
    out = text
    for pat, repl in SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


def export_bundle(root: Path, entries: List[FileEntry], *, do_redact: bool) -> str:
    include_paths = [e.abs_path for e in entries]

    parts: List[str] = []
    parts.append(build_tree(root, include_paths, DEFAULT_EXCLUDE_DIRS))
    parts.append("\n# =====================\n# Files (export)\n# =====================\n")

    for e in entries:
        content = read_text(e.abs_path)
        if do_redact:
            content = redact(content)

        parts.append(f"\n# ---------- {e.rel_path} ----------\n")
        # Header que você pediu: comentário antes de imports
        parts.append(f"#{e.rel_path}\n")
        parts.append(content.rstrip() + "\n")

    return "".join(parts)


def main():
    ap = argparse.ArgumentParser(description="Exporta bot/ + run.py num bundle único para colar como prompt raiz.")
    ap.add_argument("--root", default=".", help="Raiz do repo (default: .)")
    ap.add_argument("--out", default="prompt_root_export.txt", help="Arquivo de saída")
    ap.add_argument("--no-bot", action="store_true", help="Não incluir bot/")
    ap.add_argument("--no-run", action="store_true", help="Não incluir run.py")
    ap.add_argument("--extra", action="append", default=[], help="Caminhos extras relativos à raiz (pode repetir)")
    ap.add_argument("--redact", action="store_true", help="Tenta mascarar tokens/segredos (heurístico)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    entries = collect_files(
        root,
        include_bot=not args.no_bot,
        include_run=not args.no_run,
        extra=args.extra,
        exclude_dirs=set(DEFAULT_EXCLUDE_DIRS),
        exclude_globs=set(DEFAULT_EXCLUDE_GLOBS),
    )
    bundle = export_bundle(root, entries, do_redact=bool(args.redact))
    out_path = root / args.out
    out_path.write_text(bundle, encoding="utf-8")
    print(f"[OK] Exportado {len(entries)} arquivos para: {out_path}")


if __name__ == "__main__":
    main()
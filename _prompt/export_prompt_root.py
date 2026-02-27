# _prompt/export_prompt_root.py
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set
import zipfile


# -----------------------------------------------------------------------------
# Hardcoded export policy (edite aqui e rode com F5)
# -----------------------------------------------------------------------------
BOT_FOLDER_POLICY: Dict[str, bool] = {
    "bot/ares_wrapper": True,
    "bot/intel": True,
    "bot/mind": True,
    "bot/planners": True,
    "bot/sensors": True,
    "bot/tasks": True,
}

# Inclui .py diretamente dentro de bot/
BOT_TOP_LEVEL_FILES_FULL: bool = True

# Arquivos da raiz opcionais
ROOT_FILES: List[str] = [
    "terran_builds.yml",
    #"config.yml",
    "run.py",
    "ARCHITECTURE.md",
    #"_prompt/root.txt",
]
INCLUDE_ROOT_FILES: bool = True

# Include extensoes (altere se quiser incluir mais)
SCRIPT_EXTENSIONS: Set[str] = {".py"}

# Saida (hardcoded)
OUTPUT_FOLDER_NAME: str = "export_scripts"
OUTPUT_ZIP_NAME: str = "export_scripts_bundle.zip"

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
    "logs",  # nunca exportar logs
}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def normalize_rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


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


def gather_files(repo_root: Path, *, exclude_dirs: Set[str]) -> List[Path]:
    out: List[Path] = []

    # bot/*.py top-level
    bot_dir = repo_root / "bot"
    if BOT_TOP_LEVEL_FILES_FULL and bot_dir.exists() and bot_dir.is_dir():
        for p in sorted(bot_dir.glob("*.py"), key=lambda x: normalize_rel(x, repo_root).lower()):
            if p.is_file() and not is_excluded(p, root=repo_root, exclude_dirs=exclude_dirs):
                if p.suffix.lower() in SCRIPT_EXTENSIONS:
                    out.append(p)

    # bot subfolders by policy
    for folder_rel, include_full in BOT_FOLDER_POLICY.items():
        if not include_full:
            continue
        folder = repo_root / folder_rel
        if not folder.exists() or not folder.is_dir():
            continue
        files = [x for x in folder.rglob("*") if x.is_file()]
        files.sort(key=lambda x: normalize_rel(x, repo_root).lower())
        for p in files:
            if is_excluded(p, root=repo_root, exclude_dirs=exclude_dirs):
                continue
            if p.suffix.lower() in SCRIPT_EXTENSIONS:
                out.append(p)

    # optional root files
    if INCLUDE_ROOT_FILES:
        for rel in ROOT_FILES:
            p = repo_root / rel
            if p.exists() and p.is_file() and not is_excluded(p, root=repo_root, exclude_dirs=exclude_dirs):
                out.append(p)

    # dedupe preserving order
    seen = set()
    deduped: List[Path] = []
    for p in out:
        key = str(p.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    return deduped


def rel_to_txt_path(rel: str) -> str:
    # Ex: bot/mind/self.py -> files/bot/mind/self.py.txt
    return f"files/{rel}.txt"


def render_txt_for_file(path: Path, *, repo_root: Path) -> str:
    rel = normalize_rel(path, repo_root)
    content = read_text_file(path)
    if not content.endswith("\n"):
        content += "\n"
    return f"# {rel}\n\n{content}"


def write_export(repo_root: Path) -> Path:
    out_dir = repo_root / "_prompt" / OUTPUT_FOLDER_NAME
    out_zip = repo_root / "_prompt" / OUTPUT_ZIP_NAME

    out_dir.mkdir(parents=True, exist_ok=True)

    files = gather_files(repo_root, exclude_dirs=DEFAULT_EXCLUDE_DIRS)

    # Limpa apenas arquivos txt antigos desse export
    for old in out_dir.rglob("*.txt"):
        try:
            old.unlink()
        except Exception:
            pass

    manifest_lines: List[str] = []
    manifest_lines.append("EXPORT META")
    manifest_lines.append(f"generated_at_utc: {datetime.now(timezone.utc).isoformat()}")
    manifest_lines.append(f"repo_root: {repo_root}")
    manifest_lines.append(f"files_total: {len(files)}")
    manifest_lines.append("")
    manifest_lines.append("FILES")

    for src in files:
        rel = normalize_rel(src, repo_root)
        txt_rel = rel_to_txt_path(rel)
        dst = out_dir / txt_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(render_txt_for_file(src, repo_root=repo_root), encoding="utf-8")
        manifest_lines.append(f"- {rel} -> {txt_rel}")

    manifest_path = out_dir / "manifest.txt"
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    # (Re)gera zip
    if out_zip.exists():
        out_zip.unlink()

    with zipfile.ZipFile(out_zip, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(out_dir.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=str(p.relative_to(out_dir)).replace("\\", "/"))

    return out_zip


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    out_zip = write_export(repo_root)
    print(f"OK: zip generated at {out_zip}")


if __name__ == "__main__":
    main()

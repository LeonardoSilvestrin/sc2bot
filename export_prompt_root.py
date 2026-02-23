# export_repo_dump.py
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable, List, Set, Tuple


DEFAULT_EXCLUDE_DIRS = {
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
    ".vscode",   # normalmente não interessa no dumpm,
    "ares-sc2"
}


def normalize_rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def should_exclude_dir(dir_name: str, exclude_dirs: Set[str]) -> bool:
    return dir_name in exclude_dirs


def build_tree(root: Path, exclude_dirs: Set[str]) -> str:
    """
    Produz uma árvore no estilo:
    .
    ├── bot
    │   ├── main.py
    │   └── ...
    └── terran_builds.yml
    """
    # Coleta todos os paths (dirs e files) respeitando exclusões
    entries: List[Tuple[Path, bool]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirpath_p = Path(dirpath)

        # filtra dirs in-place para o os.walk não descer nelas
        dirnames[:] = sorted([d for d in dirnames if not should_exclude_dir(d, exclude_dirs)])
        filenames[:] = sorted(filenames)

        # registra diretórios e arquivos
        for d in dirnames:
            entries.append((dirpath_p / d, True))
        for f in filenames:
            entries.append((dirpath_p / f, False))

    # Ordena por caminho relativo, com diretórios primeiro quando empate
    entries.sort(key=lambda x: (normalize_rel(x[0], root), 0 if x[1] else 1))

    # Constrói uma estrutura hierárquica simples (set de paths) pra desenhar a árvore
    # Vamos desenhar usando o padrão de prefixos por nível.
    # Primeiro, pegar todos os paths relativos e separar em partes.
    rel_items = [(Path(normalize_rel(p, root)), is_dir) for p, is_dir in entries]

    # Monta um mapa de filhos por diretório
    children: dict[Path, List[Tuple[str, bool]]] = {}
    # garante root como "."
    children[Path(".")] = []

    for rel_path, is_dir in rel_items:
        parent = rel_path.parent if rel_path.parent != Path("") else Path(".")
        children.setdefault(parent, [])
        children.setdefault(rel_path if is_dir else parent, children.get(rel_path if is_dir else parent, []))
        children[parent].append((rel_path.name, is_dir))

    # Remove duplicatas e ordena filhos (dirs primeiro, depois files)
    for parent in list(children.keys()):
        uniq = {}
        for name, is_dir in children[parent]:
            uniq[(name, is_dir)] = (name, is_dir)
        kids = list(uniq.values())
        kids.sort(key=lambda x: (0 if x[1] else 1, x[0].lower()))
        children[parent] = kids

    lines: List[str] = ["."]
    # DFS com prefixos
    def render_dir(dir_rel: Path, prefix: str) -> None:
        kids = children.get(dir_rel, [])
        for i, (name, is_dir) in enumerate(kids):
            is_last = i == len(kids) - 1
            branch = "└── " if is_last else "├── "
            lines.append(prefix + branch + name)
            if is_dir:
                next_prefix = prefix + ("    " if is_last else "│   ")
                render_dir(dir_rel / name, next_prefix)

    render_dir(Path("."), "")
    return "\n".join(lines) + "\n"


def read_text_file(path: Path) -> str:
    # tenta UTF-8; se quebrar, cai para cp1252 (Windows), sem explodir
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1252", errors="replace")


def gather_bot_py_files(root: Path) -> List[Path]:
    bot_dir = root / "bot"
    if not bot_dir.exists() or not bot_dir.is_dir():
        return []
    files = sorted([p for p in bot_dir.rglob("*.py") if p.is_file()], key=lambda p: str(p).lower())
    return files


def write_dump(
    root: Path,
    out_path: Path,
    exclude_dirs: Set[str],
    include_tree: bool,
    include_bot: bool,
    include_terran_builds: bool,
) -> None:
    parts: List[str] = []

    if include_tree:
        parts.append("===== PROJECT TREE =====\n")
        parts.append(build_tree(root, exclude_dirs))
        parts.append("\n")

    if include_bot:
        py_files = gather_bot_py_files(root)
        parts.append("===== bot/*.py (FULL CONTENT) =====\n")
        if not py_files:
            parts.append("(nenhum arquivo .py encontrado em bot/)\n\n")
        else:
            for f in py_files:
                rel = normalize_rel(f, root)
                parts.append(f"\n# {rel}\n")
                parts.append("```python\n")
                parts.append(read_text_file(f))
                if not parts[-1].endswith("\n"):
                    parts.append("\n")
                parts.append("```\n")

    if include_terran_builds:
        tb = root / "terran_builds.yml"
        parts.append("\n===== terran_builds.yml (ROOT) =====\n")
        if not tb.exists():
            parts.append("(arquivo terran_builds.yml não encontrado na raiz)\n")
        else:
            parts.append(f"\n# {normalize_rel(tb, root)}\n")
            parts.append("```yaml\n")
            parts.append(read_text_file(tb))
            if not parts[-1].endswith("\n"):
                parts.append("\n")
            parts.append("```\n")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exporta árvore do repo + conteúdo de bot/*.py + terran_builds.yml para um TXT."
    )
    parser.add_argument(
        "--root",
        type=str,
        default=".",
        help="Caminho da raiz do repo (default: .).",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="export_root_dump.txt",
        help="Arquivo de saída (default: export_root_dump.txt).",
    )
    parser.add_argument(
        "--exclude-dirs",
        type=str,
        default=",".join(sorted(DEFAULT_EXCLUDE_DIRS)),
        help="Lista separada por vírgula de diretórios a excluir da árvore.",
    )
    parser.add_argument("--no-tree", action="store_true", help="Não incluir árvore de diretórios.")
    parser.add_argument("--no-bot", action="store_true", help="Não incluir conteúdo de bot/*.py.")
    parser.add_argument("--no-terran-builds", action="store_true", help="Não incluir terran_builds.yml.")

    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_path = Path(args.out).resolve()
    exclude_dirs = {d.strip() for d in args.exclude_dirs.split(",") if d.strip()}

    write_dump(
        root=root,
        out_path=out_path,
        exclude_dirs=exclude_dirs,
        include_tree=not args.no_tree,
        include_bot=not args.no_bot,
        include_terran_builds=not args.no_terran_builds,
    )

    print(f"OK: dump gerado em: {out_path}")


if __name__ == "__main__":
    main()
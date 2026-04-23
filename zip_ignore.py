#!/usr/bin/env python3
"""
zip_ignore.py - Create a ZIP archive of a project while excluding paths listed in a .zipignore file.

Usage:
  python zip_ignore.py [-o OUTPUT] [-i IGNOREFILE] [ROOT]

Arguments:
  ROOT         Project root to archive (default: current directory).

Options:
  -o, --output      Output ZIP filename or path. If placed inside ROOT,
                    the archive is automatically excluded from itself.
                    [default: project.zip]
  -i, --ignorefile  Ignore file (gitignore-style patterns). [default: .zipignore]

Patterns:
  The ignore file uses gitignore-style semantics via `pathspec`.
  Empty lines and lines starting with '#' are ignored.
  Examples:
    .git/
    .idea/
    .venv/
    __pycache__/
    *.log
    data/raw/**
"""

from __future__ import annotations

import argparse
import os
import zipfile
from pathlib import Path
from typing import Iterable, List, Optional

from pathspec import PathSpec


def read_ignore_patterns(ignore_path: Path) -> List[str]:
    """
    Read ignore patterns from `ignore_path`, stripping comments and blanks.
    Returns an empty list if the file does not exist.
    """
    if not ignore_path.exists():
        return []
    lines = ignore_path.read_text(encoding="utf-8").splitlines()
    patterns: List[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        patterns.append(s)
    return patterns


def build_spec(patterns: Iterable[str]) -> PathSpec:
    """
    Build a PathSpec using gitignore-style semantics.
    """
    return PathSpec.from_lines("gitignore", patterns)


def rel_posix(path: Path, root: Path) -> str:
    """
    Return a POSIX-style relative path from `root` to `path`, suitable for PathSpec.
    """
    return path.relative_to(root).as_posix()


def is_relative_to(path: Path, root: Path) -> bool:
    """
    Return True when `path` is inside `root`, compatible with Python < 3.9.
    """
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def create_archive(root: Path, output_zip: Path, spec: PathSpec) -> None:
    """
    Walk `root` and write files to `output_zip`, skipping any path matched by `spec`
    and skipping the archive file itself if it resides under `root`.
    """
    root = root.resolve()
    output_zip = output_zip.resolve()

    archive_rel_posix: Optional[str] = None
    if is_relative_to(output_zip, root):
        archive_rel_posix = rel_posix(output_zip, root)

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            filenames.sort()

            dirpath_p = Path(dirpath)
            for fname in filenames:
                f_path = dirpath_p / fname
                rel_file = rel_posix(f_path, root)

                if archive_rel_posix and rel_file == archive_rel_posix:
                    continue

                if spec.match_file(rel_file):
                    continue

                zf.write(f_path, rel_file)


def parse_args() -> argparse.Namespace:
    """
    Parse CLI arguments.
    """
    p = argparse.ArgumentParser(
        description="Create a ZIP archive of a project while excluding .zipignore patterns."
    )
    p.add_argument("root", nargs="?", default=".", help="Project root (default: .)")
    p.add_argument(
        "-o",
        "--output",
        default="project.zip",
        help="Output ZIP filename/path (default: project.zip)",
    )
    p.add_argument(
        "-i",
        "--ignorefile",
        default=".zipignore",
        help="Ignore file with gitignore-style patterns (default: .zipignore)",
    )
    return p.parse_args()


def main() -> None:
    """
    Entry point: build PathSpec from ignore file, then create the archive.
    """
    args = parse_args()
    root = Path(args.root).resolve()
    output_zip = Path(args.output).resolve()

    if not root.exists():
        raise SystemExit(f"Root path does not exist: {root}")
    if not root.is_dir():
        raise SystemExit(f"Root path is not a directory: {root}")

    ignore_arg_path = Path(args.ignorefile)
    ignorefile = ignore_arg_path if ignore_arg_path.is_absolute() else root / ignore_arg_path
    ignorefile = ignorefile.resolve()

    patterns = read_ignore_patterns(ignorefile)
    spec = build_spec(patterns)

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    create_archive(root, output_zip, spec)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
zip_ignore.py - Create a ZIP archive of a project while excluding paths listed in a .zipignore file.
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


def create_archive(root: Path, output_zip: Path, spec: PathSpec, verbose: bool = False) -> None:
    """
    Walk `root` and write files to `output_zip`, skipping paths matched by `spec`.
    """
    root = root.resolve()
    output_zip = output_zip.resolve()

    archive_rel_posix: Optional[str] = None
    if is_relative_to(output_zip, root):
        archive_rel_posix = rel_posix(output_zip, root)

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(root):
            dirpath_p = Path(dirpath)
            
            # ВАЖНО: Фильтруем директории in-place ДО того, как os.walk в них спустится.
            # Добавляем "/", чтобы pathspec корректно обрабатывал паттерны папок (например, "build/").
            dirnames[:] = [
                d for d in dirnames
                if not spec.match_file(rel_posix(dirpath_p / d, root) + "/")
            ]

            dirnames.sort()
            filenames.sort()

            for fname in filenames:
                f_path = dirpath_p / fname
                rel_file = rel_posix(f_path, root)

                if archive_rel_posix and rel_file == archive_rel_posix:
                    continue

                if spec.match_file(rel_file):
                    continue

                if verbose:
                    print(f"Adding: {rel_file}")
                
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
        "--ignore-file",
        default=".zipignore",
        help="Ignore file with gitignore-style patterns (default: .zipignore)",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print added files to stdout",
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

    # Элегантное решение с путями: pathlib сам разберется, если ignore_file уже абсолютный
    ignore_arg_path = Path(args.ignore_file)
    ignore_file = (root / ignore_arg_path).resolve()

    patterns = read_ignore_patterns(ignore_file)
    spec = build_spec(patterns)

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    create_archive(root, output_zip, spec, verbose=args.verbose)


if __name__ == "__main__":
    main()
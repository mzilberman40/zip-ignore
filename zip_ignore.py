#!/usr/bin/env python3
"""
zip_ignore.py - Create a ZIP archive of a project while excluding paths listed in a .zipignore file.
"""

from __future__ import annotations

import argparse
import os
import zipfile
from pathlib import Path
from typing import Iterable, List, Optional, Set

from pathspec import PathSpec


def read_ignore_patterns(ignore_path: Path) -> List[str]:
    """
    Read raw ignore patterns from `ignore_path`.
    Raises an error if the file does not exist or cannot be read.
    """
    if not ignore_path.exists():
        raise OSError(f"Ignore file does not exist: {ignore_path}")
    try:
        lines = ignore_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise OSError(f"Cannot read ignore file '{ignore_path}': {exc}") from exc

    return lines


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


def rel_dir_posix(path: Path, root: Path) -> str:
    """
    Return a POSIX-style relative directory path with a trailing slash.
    """
    return f"{rel_posix(path, root)}/"


def is_relative_to(path: Path, root: Path) -> bool:
    """
    Return True when `path` is inside `root`, compatible with Python < 3.9.
    """
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def negation_walk_prefixes(spec: PathSpec) -> Set[str]:
    """
    Return directory prefixes that must be traversed to honor negation patterns.
    """
    prefixes: Set[str] = set()

    for pattern in spec.patterns:
        if getattr(pattern, "include", None) is not False:
            continue

        raw_pattern = getattr(pattern, "pattern", "")
        if not raw_pattern.startswith("!"):
            continue

        negated = raw_pattern[1:].rstrip()
        if not negated:
            continue

        negated = negated.lstrip("/")
        if not negated:
            continue

        parts = [part for part in negated.split("/") if part]
        if not parts:
            continue

        walk_parts: List[str] = []
        for part in parts[:-1]:
            if any(ch in part for ch in "*?["):
                break
            walk_parts.append(part)
            prefixes.add("/".join(walk_parts))

    return prefixes


def create_archive(root: Path, output_zip: Path, spec: PathSpec, verbose: bool = False) -> None:
    """
    Walk `root` and write files to `output_zip`, skipping paths matched by `spec`.
    """
    root = root.resolve()
    output_zip = output_zip.resolve()

    archive_rel_posix: Optional[str] = None
    if is_relative_to(output_zip, root):
        archive_rel_posix = rel_posix(output_zip, root)

    preserved_prefixes = negation_walk_prefixes(spec)

    try:
        with zipfile.ZipFile(
            output_zip,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            strict_timestamps=False,
        ) as zf:
            for dirpath, dirnames, filenames in os.walk(root):
                dirpath_p = Path(dirpath)

                dirnames.sort()
                filenames.sort()

                # Prune ignored directories unless a negation pattern needs us to walk through them.
                dirnames[:] = [
                    dirname
                    for dirname in dirnames
                    if (
                        not spec.match_file(rel_dir_posix(dirpath_p / dirname, root))
                        or rel_posix(dirpath_p / dirname, root) in preserved_prefixes
                    )
                ]

                for fname in filenames:
                    f_path = dirpath_p / fname
                    rel_file = rel_posix(f_path, root)

                    if archive_rel_posix and rel_file == archive_rel_posix:
                        continue

                    if spec.match_file(rel_file):
                        continue

                    if verbose:
                        print(f"Adding: {rel_file}")
                    try:
                        zf.write(f_path, rel_file)
                    except (OSError, ValueError) as exc:
                        raise OSError(
                            f"Cannot write '{f_path}' to archive '{output_zip}': {exc}"
                        ) from exc
    except (OSError, ValueError) as exc:
        raise OSError(f"Cannot create archive '{output_zip}': {exc}") from exc


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

    # Elegant path handling: pathlib resolves both relative and absolute ignore paths.
    ignore_arg_path = Path(args.ignore_file)
    ignore_file = (root / ignore_arg_path).resolve()

    try:
        patterns = read_ignore_patterns(ignore_file)
        spec = build_spec(patterns)
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        create_archive(root, output_zip, spec, verbose=args.verbose)
    except OSError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()

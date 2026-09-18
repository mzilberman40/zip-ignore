#!/usr/bin/env python3
"""
zip_ignore.py - Create compact, review-friendly ZIP snapshots while respecting .zipignore rules.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from pathspec import PathSpec


__version__ = "0.2.1"
MANIFEST_NAME = "SNAPSHOT_MANIFEST.txt"
DEFAULT_PROFILE = "review"
PROFILES = ("context", "review", "changed", "full")

# Low-value/generated content excluded from normal AI/review snapshots even when a
# repository forgot to list it in .zipignore. The full profile intentionally does
# not apply these patterns.
REVIEW_EXCLUDE_PATTERNS = [
    ".git/",
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".hypothesis/",
    ".tox/",
    ".nox/",
    ".cache/",
    "htmlcov/",
    "coverage/",
    ".coverage",
    ".coverage.*",
    "coverage.xml",
    "junit*.xml",
    "test-results/",
    "playwright-report/",
    "node_modules/",
    "build/",
    "dist/",
    "*.egg-info/",
    ".next/",
    ".vite/",
]

CONTEXT_EXCLUDE_PATTERNS = REVIEW_EXCLUDE_PATTERNS + [
    "tests/",
    "test/",
    "**/tests/",
    "**/__tests__/",
    "test_*.py",
    "*_test.py",
    "*.test.js",
    "*.test.jsx",
    "*.test.ts",
    "*.test.tsx",
    "*.spec.js",
    "*.spec.jsx",
    "*.spec.ts",
    "*.spec.tsx",
]

SAFE_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")


@dataclass
class GitMetadata:
    available: bool
    branch: Optional[str] = None
    head: Optional[str] = None
    status_lines: Optional[List[str]] = None


@dataclass
class SnapshotResult:
    profile: str
    selection_mode: str
    included_files: List[str]
    skipped_counts: Dict[str, int]
    source_bytes: int
    archive_bytes: int
    git: GitMetadata


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
    """Build a PathSpec using gitignore-style semantics."""
    return PathSpec.from_lines("gitignore", patterns)


def rel_posix(path: Path, root: Path) -> str:
    """Return a POSIX-style relative path from `root` to `path`."""
    return path.relative_to(root).as_posix()


def rel_dir_posix(path: Path, root: Path) -> str:
    """Return a POSIX-style relative directory path with a trailing slash."""
    return f"{rel_posix(path, root)}/"


def is_relative_to(path: Path, root: Path) -> bool:
    """Return True when `path` is inside `root`, compatible with Python < 3.9."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def default_archive_name(root: Path, created_at: Optional[datetime] = None) -> str:
    """Return the default archive filename for `root`."""
    created_at = created_at or datetime.now()
    folder_name = root.resolve().name
    timestamp = created_at.strftime("%Y%m%d_%H%M%S")
    return f"{folder_name}_{timestamp}.zip"


def negation_walk_prefixes(spec: PathSpec) -> Set[str]:
    """Return directory prefixes that must be traversed to honour negation patterns."""
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
    Backwards-compatible low-level archive helper.

    New CLI behaviour uses `create_snapshot`; this function intentionally retains
    the 0.1.x semantics for callers/tests that use it directly.
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
            compresslevel=9,
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


def _run_git(root: Path, args: Sequence[str], check: bool = True) -> subprocess.CompletedProcess:
    command = ["git", "-C", str(root)] + list(args)
    try:
        return subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
        )
    except FileNotFoundError as exc:
        raise OSError("Git executable was not found") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        raise OSError(stderr or f"Git command failed: {' '.join(command)}") from exc


def is_git_repository(root: Path) -> bool:
    """Return True when `root` is inside a Git work tree."""
    if shutil.which("git") is None:
        return False
    result = _run_git(root, ["rev-parse", "--is-inside-work-tree"], check=False)
    return result.returncode == 0 and result.stdout.decode("utf-8", errors="replace").strip() == "true"


def _decode_nul_paths(data: bytes) -> List[str]:
    return [item.decode("utf-8", errors="surrogateescape") for item in data.split(b"\0") if item]


def collect_git_candidates(root: Path) -> List[Path]:
    """Return tracked plus untracked/non-ignored files from Git."""
    result = _run_git(root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    candidates = []
    for rel in _decode_nul_paths(result.stdout):
        path = root / rel
        if path.exists() and path.is_file():
            candidates.append(path)
    return sorted(candidates, key=lambda path: rel_posix(path, root))


def collect_git_changed_candidates(root: Path) -> List[Path]:
    """Return staged, unstaged, and untracked/non-ignored files in the working tree."""
    paths: Set[str] = set()
    commands = [
        ["diff", "--name-only", "-z", "--diff-filter=ACMRTUXB"],
        ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRTUXB"],
        ["ls-files", "-z", "--others", "--exclude-standard"],
    ]
    for command in commands:
        paths.update(_decode_nul_paths(_run_git(root, command).stdout))

    candidates = []
    for rel in paths:
        path = root / rel
        if path.exists() and path.is_file():
            candidates.append(path)
    return sorted(candidates, key=lambda path: rel_posix(path, root))


def collect_filesystem_candidates(root: Path, repository_spec: PathSpec) -> List[Path]:
    """Fallback file discovery for non-Git directories."""
    candidates: List[Path] = []
    preserved_prefixes = negation_walk_prefixes(repository_spec)

    for dirpath, dirnames, filenames in os.walk(root):
        dirpath_p = Path(dirpath)
        dirnames.sort()
        filenames.sort()

        # Repository ignores are safe to prune while preserving explicit negations.
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if (
                not repository_spec.match_file(rel_dir_posix(dirpath_p / dirname, root))
                or rel_posix(dirpath_p / dirname, root) in preserved_prefixes
            )
        ]

        for filename in filenames:
            path = dirpath_p / filename
            if path.is_file():
                candidates.append(path)

    return candidates


def get_git_metadata(root: Path) -> GitMetadata:
    if not is_git_repository(root):
        return GitMetadata(available=False, status_lines=[])

    branch = _run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.decode(
        "utf-8", errors="replace"
    ).strip()
    head = _run_git(root, ["rev-parse", "HEAD"]).stdout.decode("utf-8", errors="replace").strip()
    status_text = _run_git(root, ["status", "--short"]).stdout.decode("utf-8", errors="replace")
    status_lines = [line for line in status_text.splitlines() if line]
    return GitMetadata(available=True, branch=branch, head=head, status_lines=status_lines)


def is_sensitive_path(relative_path: str) -> bool:
    """
    Conservative guard for common credential/private-key files.

    Template/sample variants are allowed. The guard is deliberately independent
    of .zipignore and cannot be bypassed by --include.
    """
    posix = relative_path.replace("\\", "/")
    lower = posix.lower()
    name = Path(posix).name.lower()

    if name.endswith(SAFE_TEMPLATE_SUFFIXES):
        return False

    if name == ".env" or name.startswith(".env."):
        return True

    if name in {".netrc", ".npmrc", ".pypirc", "credentials.json", "kubeconfig"}:
        return True

    if lower.endswith("/.aws/credentials") or lower == ".aws/credentials":
        return True
    if lower.endswith("/.kube/config") or lower == ".kube/config":
        return True
    if lower.endswith("/.docker/config.json") or lower == ".docker/config.json":
        return True

    if name in {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}:
        return True
    if name.endswith((".pem", ".key", ".p12", ".pfx")):
        return True
    if name.endswith((".tfvars", ".auto.tfvars")):
        return True
    if name.startswith("service-account") and name.endswith(".json"):
        return True
    if name.startswith("service_account") and name.endswith(".json"):
        return True

    return False


def profile_patterns(profile: str) -> List[str]:
    if profile == "context":
        return CONTEXT_EXCLUDE_PATTERNS
    if profile in {"review", "changed"}:
        return REVIEW_EXCLUDE_PATTERNS
    if profile == "full":
        return []
    raise ValueError(f"Unknown profile: {profile}")


def select_snapshot_files(
    root: Path,
    output_zip: Path,
    repository_spec: PathSpec,
    profile: str,
    include_patterns: Sequence[str] = (),
    exclude_patterns: Sequence[str] = (),
) -> Tuple[List[Path], Dict[str, int], str, GitMetadata]:
    """Select files for a snapshot and return files, skip counters, mode, and Git metadata."""
    root = root.resolve()
    output_zip = output_zip.resolve()
    git = get_git_metadata(root)

    if profile == "changed":
        if not git.available:
            raise OSError("The 'changed' profile requires a Git work tree")
        candidates = collect_git_changed_candidates(root)
        selection_mode = "git-changed"
    elif git.available:
        candidates = collect_git_candidates(root)
        selection_mode = "git-tracked+untracked"
    else:
        candidates = collect_filesystem_candidates(root, repository_spec)
        selection_mode = "filesystem-fallback"

    profile_spec = build_spec(profile_patterns(profile))
    include_spec = build_spec(include_patterns)
    exclude_spec = build_spec(exclude_patterns)

    selected: List[Path] = []
    skipped: Dict[str, int] = defaultdict(int)

    output_rel: Optional[str] = None
    if is_relative_to(output_zip, root):
        output_rel = rel_posix(output_zip, root)

    for path in candidates:
        rel = rel_posix(path, root)

        if output_rel and rel == output_rel:
            skipped["output-archive"] += 1
            continue
        # Never dereference symlinks into snapshot contents. A harmless-looking
        # path could otherwise point outside the repository or at a sensitive file.
        if path.is_symlink():
            skipped["symlink"] += 1
            continue
        if rel == MANIFEST_NAME:
            skipped["reserved-manifest"] += 1
            continue
        if is_sensitive_path(rel):
            skipped["sensitive"] += 1
            continue
        if repository_spec.match_file(rel):
            skipped["repository-ignore"] += 1
            continue
        if exclude_patterns and exclude_spec.match_file(rel):
            skipped["cli-exclude"] += 1
            continue

        included_by_override = bool(include_patterns) and include_spec.match_file(rel)
        if profile_spec.match_file(rel) and not included_by_override:
            skipped["profile"] += 1
            continue

        selected.append(path)

    return selected, dict(skipped), selection_mode, git


def _format_manifest(
    root: Path,
    profile: str,
    selection_mode: str,
    files: Sequence[Path],
    skipped_counts: Dict[str, int],
    source_bytes: int,
    git: GitMetadata,
) -> str:
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    lines = [
        "zip-ignore snapshot manifest",
        f"tool_version: {__version__}",
        f"created_utc: {created}",
        f"repository: {root.name}",
        f"profile: {profile}",
        f"selection_mode: {selection_mode}",
        f"included_files: {len(files)}",
        f"included_source_bytes: {source_bytes}",
    ]

    if skipped_counts:
        lines.append("skipped:")
        for reason in sorted(skipped_counts):
            lines.append(f"  {reason}: {skipped_counts[reason]}")
    else:
        lines.append("skipped: none")

    if git.available:
        lines.extend(
            [
                "git:",
                f"  branch: {git.branch or 'unknown'}",
                f"  head: {git.head or 'unknown'}",
                f"  worktree: {'modified' if git.status_lines else 'clean'}",
            ]
        )
        if git.status_lines:
            lines.append("  status_short:")
            lines.extend(f"    {line}" for line in git.status_lines)
    else:
        lines.append("git: unavailable-or-not-a-worktree")

    lines.append("files:")
    lines.extend(f"  {rel_posix(path, root)}" for path in files)
    lines.append("")
    return "\n".join(lines)


def create_snapshot(
    root: Path,
    output_zip: Path,
    repository_spec: PathSpec,
    profile: str = DEFAULT_PROFILE,
    include_patterns: Sequence[str] = (),
    exclude_patterns: Sequence[str] = (),
    verbose: bool = False,
) -> SnapshotResult:
    """Create a profile-aware, Git-aware snapshot ZIP with an embedded manifest."""
    root = root.resolve()
    output_zip = output_zip.resolve()

    files, skipped, selection_mode, git = select_snapshot_files(
        root=root,
        output_zip=output_zip,
        repository_spec=repository_spec,
        profile=profile,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
    )

    try:
        source_bytes = sum(path.stat().st_size for path in files)
    except OSError as exc:
        raise OSError(f"Cannot stat snapshot input: {exc}") from exc

    manifest = _format_manifest(
        root=root,
        profile=profile,
        selection_mode=selection_mode,
        files=files,
        skipped_counts=skipped,
        source_bytes=source_bytes,
        git=git,
    )

    try:
        with zipfile.ZipFile(
            output_zip,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=False,
        ) as zf:
            for path in files:
                rel = rel_posix(path, root)
                if verbose:
                    print(f"Adding: {rel}")
                zf.write(path, rel)
            zf.writestr(MANIFEST_NAME, manifest)
    except (OSError, ValueError) as exc:
        raise OSError(f"Cannot create archive '{output_zip}': {exc}") from exc

    try:
        archive_bytes = output_zip.stat().st_size
    except OSError as exc:
        raise OSError(f"Cannot stat archive '{output_zip}': {exc}") from exc

    return SnapshotResult(
        profile=profile,
        selection_mode=selection_mode,
        included_files=[rel_posix(path, root) for path in files],
        skipped_counts=skipped,
        source_bytes=source_bytes,
        archive_bytes=archive_bytes,
        git=git,
    )


def format_size(size: int) -> str:
    value = float(size)
    units = ["B", "KiB", "MiB", "GiB"]
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{size} B"


def print_size_report(root: Path, output_zip: Path, result: SnapshotResult) -> None:
    print(f"Created: {output_zip}")
    print(f"Profile: {result.profile} ({result.selection_mode})")
    print(
        f"Included: {len(result.included_files)} files, "
        f"{format_size(result.source_bytes)} -> {format_size(result.archive_bytes)} ZIP"
    )

    if result.skipped_counts:
        skipped = ", ".join(
            f"{reason}={count}" for reason, count in sorted(result.skipped_counts.items())
        )
        print(f"Skipped: {skipped}")

    groups: Dict[str, int] = defaultdict(int)
    largest: List[Tuple[int, str]] = []
    for rel in result.included_files:
        path = root / rel
        try:
            size = path.stat().st_size
        except OSError:
            continue
        top = rel.split("/", 1)[0] if "/" in rel else "(root)"
        groups[top] += size
        largest.append((size, rel))

    if groups:
        print("Largest groups:")
        for group, size in sorted(groups.items(), key=lambda item: item[1], reverse=True)[:5]:
            print(f"  {group:<24} {format_size(size):>10}")

    if largest:
        print("Largest files:")
        for size, rel in sorted(largest, reverse=True)[:5]:
            print(f"  {rel:<48} {format_size(size):>10}")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Create a compact ZIP snapshot using .zipignore rules, Git-aware file selection, "
            "profile filtering, and a hard secret-file guard."
        ),
        epilog=(
            "Profile semantics:\n"
            "  context  Git-aware candidates, then .zipignore/guards, then built-in exclusions\n"
            "           for tests and common generated artefacts.\n"
            "  review   Git-aware candidates, then .zipignore/guards, then built-in exclusions\n"
            "           for common generated artefacts; tests remain included.\n"
            "  changed  Only staged/unstaged/untracked Git changes, then the same filtering as\n"
            "           review. Requires a Git work tree.\n"
            "  full     Disables only built-in profile exclusions. Git-ignore rules, .zipignore,\n"
            "           the secret/symlink guards, --exclude, and output self-exclusion still apply.\n"
            "\n"
            "Important: --include can override only built-in profile exclusions. It cannot restore\n"
            "Git-ignored files, .zipignore matches, --exclude matches, secrets, or symlinks."
        ),
    )
    p.add_argument("root", nargs="?", default=".", help="Project root (default: .)")
    p.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output ZIP filename/path (default: ROOT_YYYYMMDD_HHMMSS.zip)",
    )
    p.add_argument(
        "-i",
        "--ignore-file",
        default=".zipignore",
        help="Ignore file with gitignore-style patterns (default: .zipignore)",
    )
    p.add_argument(
        "-p",
        "--profile",
        choices=PROFILES,
        default=DEFAULT_PROFILE,
        help=(
            "Snapshot profile: context excludes tests; review includes tests but excludes common "
            "generated artefacts; changed includes only current Git changes; full disables only "
            "built-in profile exclusions while .zipignore and safety guards still apply "
            "(default: review)"
        ),
    )
    p.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="PATTERN",
        help=(
            "Re-include files excluded only by the selected profile (repeatable; cannot bypass "
            "Git ignore, .zipignore, --exclude, secret guard, or symlink guard)"
        ),
    )
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Additional gitignore-style exclusion pattern (repeatable)",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Print each added file")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


def main() -> None:
    """Entry point."""
    args = parse_args()
    root = Path(args.root).resolve()
    output_zip = Path(args.output or default_archive_name(root)).resolve()

    if not root.exists():
        raise SystemExit(f"Root path does not exist: {root}")
    if not root.is_dir():
        raise SystemExit(f"Root path is not a directory: {root}")

    ignore_arg_path = Path(args.ignore_file)
    ignore_file = ignore_arg_path if ignore_arg_path.is_absolute() else root / ignore_arg_path
    ignore_file = ignore_file.resolve()

    try:
        patterns = read_ignore_patterns(ignore_file)
        repository_spec = build_spec(patterns)
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        result = create_snapshot(
            root=root,
            output_zip=output_zip,
            repository_spec=repository_spec,
            profile=args.profile,
            include_patterns=args.include,
            exclude_patterns=args.exclude,
            verbose=args.verbose,
        )
        print_size_report(root, output_zip, result)
    except OSError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()

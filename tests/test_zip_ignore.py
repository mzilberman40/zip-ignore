import io
import os
import shutil
import subprocess
import unittest
import zipfile
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from zip_ignore import (
    build_spec,
    create_archive,
    default_archive_name,
    is_relative_to,
    read_ignore_patterns,
    rel_posix,
    create_snapshot,
    get_git_metadata,
    is_sensitive_path,
    select_snapshot_files,
)


class ZipIgnoreTests(unittest.TestCase):
    def make_case_root(self, name: str) -> Path:
        root = Path(__file__).resolve().parent / name
        if root.exists(): shutil.rmtree(root)
        root.mkdir()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def test_read_ignore_patterns_nonexistent_file_raises(self) -> None:
        nonexistent = Path("nonexistent.zipignore")
        with self.assertRaises(OSError):
            read_ignore_patterns(nonexistent)

    def test_read_ignore_patterns_preserves_raw_lines(self) -> None:
        root = self.make_case_root("_case_ignore_patterns")
        ignore_file = root / ".zipignore"
        ignore_file.write_text("""
# This is a comment
*.tmp

   # Another comment with spaces
__pycache__/

# Empty line above
""")
        patterns = read_ignore_patterns(ignore_file)
        self.assertEqual(
            patterns,
            [
                "",
                "# This is a comment",
                "*.tmp",
                "",
                "   # Another comment with spaces",
                "__pycache__/",
                "",
                "# Empty line above",
            ],
        )

    def test_read_ignore_patterns_raises_on_directory(self) -> None:
        root = self.make_case_root("_case_ignore_dir_error")
        with self.assertRaises(OSError):
            read_ignore_patterns(root)

    def test_rel_posix(self) -> None:
        root = Path("/root")
        path = Path("/root/sub/file.txt")
        self.assertEqual(rel_posix(path, root), "sub/file.txt")

    def test_is_relative_to(self) -> None:
        root = Path("/root")
        inside = Path("/root/sub")
        outside = Path("/other")
        self.assertTrue(is_relative_to(inside, root))
        self.assertFalse(is_relative_to(outside, root))

    def test_default_archive_name_includes_folder_name_and_creation_time(self) -> None:
        root = self.make_case_root("_case_default_name")
        created_at = datetime(2026, 5, 1, 13, 45, 9)

        self.assertEqual(
            default_archive_name(root, created_at),
            "_case_default_name_20260501_134509.zip",
        )

    def test_output_archive_is_not_added_to_itself(self) -> None:
        root = self.make_case_root("_case_self_exclusion")
        (root / "data.txt").write_text("payload")
        output_zip = root / "archive.zip"
        spec = build_spec([])
        create_archive(root, output_zip, spec)
        with zipfile.ZipFile(output_zip) as archive:
            self.assertNotIn("archive.zip", archive.namelist())

    def test_verbose_mode_output(self) -> None:
        root = self.make_case_root("_case_verbose")
        (root / "file.txt").write_text("data")
        f = io.StringIO()
        with redirect_stdout(f):
            create_archive(root, root / "archive.zip", build_spec([]), verbose=True)
        self.assertIn("Adding: file.txt", f.getvalue())

    def test_create_archive_raises_for_invalid_output_path(self) -> None:
        root = self.make_case_root("_case_invalid_output")
        (root / "input.txt").write_text("data")
        invalid_parent = root / "parent_file"
        invalid_parent.write_text("not a dir")
        output_zip = invalid_parent / "archive.zip"

        with self.assertRaises(OSError):
            create_archive(root, output_zip, build_spec([]))

    def test_ignore_files(self) -> None:
        root = self.make_case_root("_case_ignore_files")
        (root / "keep.txt").write_text("keep")
        (root / "ignore.tmp").write_text("ignore")
        spec = build_spec(["*.tmp"])
        output_zip = root / "archive.zip"
        create_archive(root, output_zip, spec)
        with zipfile.ZipFile(output_zip) as archive:
            namelist = archive.namelist()
            self.assertIn("keep.txt", namelist)
            self.assertNotIn("ignore.tmp", namelist)

    def test_ignore_directories(self) -> None:
        root = self.make_case_root("_case_ignore_dirs")
        (root / "keep.txt").write_text("keep")
        ignored_dir = root / "ignored"
        ignored_dir.mkdir()
        (ignored_dir / "file.txt").write_text("ignored")
        spec = build_spec(["ignored/"])
        output_zip = root / "archive.zip"
        create_archive(root, output_zip, spec)
        with zipfile.ZipFile(output_zip) as archive:
            namelist = archive.namelist()
            self.assertIn("keep.txt", namelist)
            self.assertNotIn("ignored/file.txt", namelist)

    def test_negation_patterns(self) -> None:
        root = self.make_case_root("_case_negation")
        build_dir = root / "build"
        build_dir.mkdir()
        (build_dir / "temp.tmp").write_text("temp")
        (build_dir / "keep.txt").write_text("keep")
        spec = build_spec(["build/", "!build/keep.txt"])
        output_zip = root / "archive.zip"
        create_archive(root, output_zip, spec)
        with zipfile.ZipFile(output_zip) as archive:
            namelist = archive.namelist()
            self.assertNotIn("build/temp.tmp", namelist)
            self.assertIn("build/keep.txt", namelist)

    def test_ignored_directories_are_pruned_without_breaking_negation(self) -> None:
        root = self.make_case_root("_case_pruned_walk")
        (root / "root.txt").write_text("root")
        (root / "keep").mkdir()
        (root / "keep" / "file.txt").write_text("keep")
        (root / "ignored").mkdir()
        (root / "ignored" / "skip.txt").write_text("skip")
        (root / "build").mkdir()
        (root / "build" / "keep.txt").write_text("keep")
        output_zip = root / "archive.zip"
        visited = []

        def fake_walk(start):
            dirnames = ["ignored", "keep", "build"]
            filenames = ["root.txt", "archive.zip"]
            visited.append(Path(start).resolve())
            yield str(start), dirnames, filenames

            if "ignored" in dirnames:
                visited.append((Path(start) / "ignored").resolve())
                yield str(Path(start) / "ignored"), [], ["skip.txt"]

            if "keep" in dirnames:
                visited.append((Path(start) / "keep").resolve())
                yield str(Path(start) / "keep"), [], ["file.txt"]

            if "build" in dirnames:
                visited.append((Path(start) / "build").resolve())
                yield str(Path(start) / "build"), [], ["keep.txt"]

        spec = build_spec(["ignored/", "build/", "!build/keep.txt"])
        with patch("zip_ignore.os.walk", side_effect=fake_walk):
            create_archive(root, output_zip, spec)

        self.assertNotIn((root / "ignored").resolve(), visited)
        self.assertIn((root / "build").resolve(), visited)

        with zipfile.ZipFile(output_zip) as archive:
            namelist = archive.namelist()
            self.assertIn("keep/file.txt", namelist)
            self.assertIn("build/keep.txt", namelist)
            self.assertNotIn("ignored/skip.txt", namelist)

    def test_pre_1980_timestamps_do_not_crash_archive_creation(self) -> None:
        root = self.make_case_root("_case_old_timestamp")
        old_file = root / "old.txt"
        old_file.write_text("payload")
        os.utime(old_file, (0, 0))

        output_zip = root / "archive.zip"
        create_archive(root, output_zip, build_spec([]))

        with zipfile.ZipFile(output_zip) as archive:
            self.assertIn("old.txt", archive.namelist())

    def test_nested_directories(self) -> None:
        root = self.make_case_root("_case_nested")
        sub = root / "sub"
        sub.mkdir()
        deep = sub / "deep"
        deep.mkdir()
        (deep / "file.txt").write_text("deep file")
        (root / "root.txt").write_text("root")
        spec = build_spec([])
        output_zip = root / "archive.zip"
        create_archive(root, output_zip, spec)
        with zipfile.ZipFile(output_zip) as archive:
            namelist = archive.namelist()
            self.assertIn("root.txt", namelist)
            self.assertIn("sub/deep/file.txt", namelist)

    def test_empty_directories_not_included(self) -> None:
        root = self.make_case_root("_case_empty_dir")
        empty_dir = root / "empty"
        empty_dir.mkdir()
        (root / "file.txt").write_text("file")
        spec = build_spec([])
        output_zip = root / "archive.zip"
        create_archive(root, output_zip, spec)
        with zipfile.ZipFile(output_zip) as archive:
            namelist = archive.namelist()
            self.assertIn("file.txt", namelist)
            # Empty directories are not stored in ZIP
            self.assertNotIn("empty/", namelist)


class SnapshotProfileTests(unittest.TestCase):
    def make_case_root(self, name: str) -> Path:
        root = Path(__file__).resolve().parent / name
        if root.exists():
            shutil.rmtree(root)
        root.mkdir()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def names_in_snapshot(self, root: Path, profile: str, include=(), exclude=()):
        output = root / "snapshot.zip"
        create_snapshot(
            root,
            output,
            build_spec([]),
            profile=profile,
            include_patterns=include,
            exclude_patterns=exclude,
        )
        with zipfile.ZipFile(output) as archive:
            return set(archive.namelist())

    def test_review_excludes_generated_reports_but_keeps_tests(self) -> None:
        root = self.make_case_root("_case_review_profile")
        (root / "app.py").write_text("print('app')")
        tests = root / "tests"
        tests.mkdir()
        (tests / "test_app.py").write_text("def test_app(): pass")
        htmlcov = root / "htmlcov"
        htmlcov.mkdir()
        (htmlcov / "index.html").write_text("coverage")

        names = self.names_in_snapshot(root, "review")

        self.assertIn("app.py", names)
        self.assertIn("tests/test_app.py", names)
        self.assertNotIn("htmlcov/index.html", names)
        self.assertIn("SNAPSHOT_MANIFEST.txt", names)

    def test_context_excludes_tests(self) -> None:
        root = self.make_case_root("_case_context_profile")
        (root / "app.py").write_text("print('app')")
        tests = root / "tests"
        tests.mkdir()
        (tests / "test_app.py").write_text("def test_app(): pass")

        names = self.names_in_snapshot(root, "context")

        self.assertIn("app.py", names)
        self.assertNotIn("tests/test_app.py", names)

    def test_context_include_can_restore_profile_excluded_test(self) -> None:
        root = self.make_case_root("_case_context_include")
        tests = root / "tests"
        tests.mkdir()
        (tests / "test_app.py").write_text("def test_app(): pass")

        names = self.names_in_snapshot(
            root,
            "context",
            include=("tests/test_app.py",),
        )

        self.assertIn("tests/test_app.py", names)

    def test_cli_exclude_wins_over_profile_include(self) -> None:
        root = self.make_case_root("_case_cli_exclude")
        tests = root / "tests"
        tests.mkdir()
        (tests / "test_app.py").write_text("def test_app(): pass")

        names = self.names_in_snapshot(
            root,
            "context",
            include=("tests/test_app.py",),
            exclude=("tests/**",),
        )

        self.assertNotIn("tests/test_app.py", names)

    def test_full_profile_keeps_generated_report_when_repository_allows_it(self) -> None:
        root = self.make_case_root("_case_full_profile")
        htmlcov = root / "htmlcov"
        htmlcov.mkdir()
        (htmlcov / "index.html").write_text("coverage")

        names = self.names_in_snapshot(root, "full")

        self.assertIn("htmlcov/index.html", names)

    def test_sensitive_files_are_always_excluded(self) -> None:
        root = self.make_case_root("_case_sensitive")
        (root / ".env").write_text("SECRET=do-not-share")
        (root / ".env.example").write_text("SECRET=replace-me")
        (root / "id_ed25519").write_text("private")
        (root / "app.py").write_text("print('app')")

        names = self.names_in_snapshot(
            root,
            "full",
            include=(".env", "id_ed25519"),
        )

        self.assertNotIn(".env", names)
        self.assertNotIn("id_ed25519", names)
        self.assertIn(".env.example", names)
        self.assertIn("app.py", names)

    def test_sensitive_path_detection(self) -> None:
        self.assertTrue(is_sensitive_path(".env"))
        self.assertTrue(is_sensitive_path(".env.local"))
        self.assertTrue(is_sensitive_path(".kube/config"))
        self.assertTrue(is_sensitive_path("keys/server.pem"))
        self.assertTrue(is_sensitive_path("terraform/prod.tfvars"))
        self.assertFalse(is_sensitive_path(".env.example"))
        self.assertFalse(is_sensitive_path("config/secret.yaml"))
        self.assertFalse(is_sensitive_path("README.md"))

    def test_repository_ignore_cannot_be_overridden_by_include(self) -> None:
        root = self.make_case_root("_case_repo_ignore")
        (root / "ignored.txt").write_text("ignored")
        (root / "keep.txt").write_text("keep")
        output = root / "snapshot.zip"

        create_snapshot(
            root,
            output,
            build_spec(["ignored.txt"]),
            profile="full",
            include_patterns=("ignored.txt",),
        )

        with zipfile.ZipFile(output) as archive:
            names = set(archive.namelist())
        self.assertNotIn("ignored.txt", names)
        self.assertIn("keep.txt", names)

    def test_manifest_contains_profile_and_file_list_without_absolute_root(self) -> None:
        root = self.make_case_root("_case_manifest")
        (root / "app.py").write_text("print('app')")
        output = root / "snapshot.zip"

        create_snapshot(root, output, build_spec([]), profile="review")

        with zipfile.ZipFile(output) as archive:
            manifest = archive.read("SNAPSHOT_MANIFEST.txt").decode("utf-8")
        self.assertIn("tool_version: 0.2.1", manifest)
        self.assertIn("profile: review", manifest)
        self.assertIn("app.py", manifest)
        self.assertNotIn(str(root.resolve()), manifest)

    @unittest.skipUnless(shutil.which("git"), "Git executable is required")
    def test_git_aware_selection_omits_gitignored_file_and_keeps_untracked_source(self) -> None:
        root = self.make_case_root("_case_git_aware")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / ".gitignore").write_text("ignored.bin\n")
        (root / "tracked.py").write_text("tracked")
        subprocess.run(["git", "-C", str(root), "add", ".gitignore", "tracked.py"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Test User",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "initial",
            ],
            check=True,
        )
        (root / "new.py").write_text("new")
        (root / "ignored.bin").write_text("ignored")

        output = root / "snapshot.zip"
        create_snapshot(root, output, build_spec([]), profile="review")

        with zipfile.ZipFile(output) as archive:
            names = set(archive.namelist())
        self.assertIn(".gitignore", names)
        self.assertIn("tracked.py", names)
        self.assertIn("new.py", names)
        self.assertNotIn("ignored.bin", names)
        self.assertFalse(any(name.startswith(".git/") for name in names))

    @unittest.skipUnless(shutil.which("git"), "Git executable is required")
    def test_changed_profile_contains_only_worktree_changes(self) -> None:
        root = self.make_case_root("_case_git_changed")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "changed.py").write_text("before")
        (root / "unchanged.py").write_text("same")
        subprocess.run(["git", "-C", str(root), "add", "changed.py", "unchanged.py"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Test User",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "initial",
            ],
            check=True,
        )
        (root / "changed.py").write_text("after")
        (root / "new.py").write_text("new")

        output = root / "snapshot.zip"
        create_snapshot(root, output, build_spec([]), profile="changed")

        with zipfile.ZipFile(output) as archive:
            names = set(archive.namelist())
        self.assertIn("changed.py", names)
        self.assertIn("new.py", names)
        self.assertNotIn("unchanged.py", names)

    def test_changed_profile_requires_git(self) -> None:
        root = self.make_case_root("_case_changed_no_git")
        (root / "app.py").write_text("data")
        with self.assertRaises(OSError):
            select_snapshot_files(
                root,
                root / "snapshot.zip",
                build_spec([]),
                profile="changed",
            )


class SnapshotSymlinkSafetyTests(unittest.TestCase):
    def test_snapshot_does_not_dereference_symlink(self) -> None:
        root = Path(__file__).resolve().parent / "_case_symlink_guard"
        if root.exists():
            shutil.rmtree(root)
        root.mkdir()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))

        target = root / ".env"
        target.write_text("SECRET=must-not-leak")
        link = root / "safe-looking.txt"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks are unavailable in this test environment")

        output = root / "snapshot.zip"
        result = create_snapshot(root, output, build_spec([]), profile="full")

        with zipfile.ZipFile(output) as archive:
            names = set(archive.namelist())
            payloads = [archive.read(name) for name in names]

        self.assertNotIn("safe-looking.txt", names)
        self.assertNotIn(b"SECRET=must-not-leak", payloads)
        self.assertEqual(result.skipped_counts.get("symlink"), 1)

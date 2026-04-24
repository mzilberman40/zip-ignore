import io
import os
import shutil
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from zip_ignore import build_spec, create_archive, read_ignore_patterns, rel_posix, is_relative_to


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

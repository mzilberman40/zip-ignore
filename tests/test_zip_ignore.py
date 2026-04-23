import shutil
import unittest
import zipfile
from pathlib import Path

from zip_ignore import build_spec, create_archive, read_ignore_patterns


class ZipIgnoreTests(unittest.TestCase):
    def make_case_root(self, name: str) -> Path:
        tests_dir = Path(__file__).resolve().parent
        root = tests_dir / name
        if root.exists():
            shutil.rmtree(root)
        root.mkdir()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def test_negated_file_inside_ignored_directory_is_kept(self) -> None:
        root = self.make_case_root("_case_negation")
        (root / "build").mkdir()
        (root / ".zipignore").write_text("build/\n!build/keep.txt\n", encoding="utf-8")
        (root / "build" / "keep.txt").write_text("keep", encoding="utf-8")
        (root / "build" / "drop.txt").write_text("drop", encoding="utf-8")

        output_zip = root / "archive.zip"
        spec = build_spec(read_ignore_patterns(root / ".zipignore"))
        create_archive(root, output_zip, spec)

        with zipfile.ZipFile(output_zip) as archive:
            names = sorted(archive.namelist())

        self.assertIn("build/keep.txt", names)
        self.assertNotIn("build/drop.txt", names)

    def test_output_archive_is_not_added_to_itself(self) -> None:
        root = self.make_case_root("_case_self_exclusion")
        (root / ".zipignore").write_text("", encoding="utf-8")
        (root / "data.txt").write_text("payload", encoding="utf-8")

        output_zip = root / "archive.zip"
        spec = build_spec(read_ignore_patterns(root / ".zipignore"))
        create_archive(root, output_zip, spec)

        with zipfile.ZipFile(output_zip) as archive:
            names = sorted(archive.namelist())

        self.assertIn(".zipignore", names)
        self.assertIn("data.txt", names)
        self.assertNotIn("archive.zip", names)


if __name__ == "__main__":
    unittest.main()

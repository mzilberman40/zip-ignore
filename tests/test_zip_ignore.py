import io
import shutil
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from zip_ignore import build_spec, create_archive, read_ignore_patterns

class ZipIgnoreTests(unittest.TestCase):
    def make_case_root(self, name: str) -> Path:
        root = Path(__file__).resolve().parent / name
        if root.exists(): shutil.rmtree(root)
        root.mkdir()
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

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
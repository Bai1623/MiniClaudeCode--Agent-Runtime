import tempfile
import unittest
from pathlib import Path

from storage import safe_join


class TestStorage(unittest.TestCase):
    def test_allows_nested_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertEqual(safe_join(tmpdir, "images/a.png"), Path(tmpdir, "images/a.png"))

    def test_rejects_parent_escape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError):
                safe_join(tmpdir, "../secret.txt")

    def test_rejects_same_prefix_sibling(self):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent, "data")
            root.mkdir()
            with self.assertRaises(ValueError):
                safe_join(root, "../data_backup/secret.txt")


if __name__ == "__main__":
    unittest.main()
